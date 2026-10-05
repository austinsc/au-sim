'use strict';
/* =========================================================================
   Approximately Up — circuit simulation engine (game tick model)

   Source of truth: the in-game manual (Localization.csv, "Component Delay"):
     "The game runs at a fixed rate of 60 ticks per second. Each component
      requires one tick to process and pass on a signal."
     "if you place 10 Data Routers between a Lever and a Datameter, the
      signal will take 11 ticks to travel from the Lever to the Datameter."

   Model: every block is a one-tick stage. On each tick, every block computes
   its new outputs from the outputs all blocks held at the END of the previous
   tick (double-buffered), plus its own internal state. Nothing is evaluated
   "instantly", so evaluation order never matters and every feedback loop is
   legal — exactly as in the game.

   Not modelled: Frame Quarter With Ports chains (the game treats a whole
   connected chain as one 1-tick stage; here just wire straight through and
   add a Data Router if you need the tick).
   ========================================================================= */

// Blocks that keep internal state across ticks (shown with a STATE badge in the UI).
const STATEFUL = new Set(['accumulator', 'memory', 'delay', 'differentiator', 'initializer',
  'small_disposable_battery', 'medium_disposable_battery', 'large_disposable_battery',
  'small_rechargeable_battery', 'medium_rechargeable_battery', 'large_rechargeable_battery',
  'fuse_box', 'bomb_c4', 'tnt_box', 'clima_bomb', 'decoupler_small']);

// Whether a Delay's ticks come ON TOP of the one tick every component takes.
// CONFIRMED false from the game's code (SCTick_Delay): the block writes each input into a
// 60-slot ring buffer and outputs the entry (ticks - 1) slots back, so a Delay set to N
// has a total latency of exactly N ticks (N = 1 behaves like any other block).
const DELAY_ADDS_TO_COMPONENT_TICK = false;

// The game's Differentiator knob has 12 positions with these update intervals (ticks).
const DIFF_INTERVALS = [1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60];

// Braking Point System: each tick the indicator moves this fraction of the way to its target (game code:
// 0.13929 = 1 − e^−0.15, i.e. a 9/s time constant at 60 ticks/s).
const BPS_EASE = 1 - Math.exp(-0.15);
const FLT_MAX = 3.4028234663852886e38;   // float.MaxValue: the ETA System's "no root found" marker

// inputs: port names; defaults: value an UNWIRED input reads (0 unless the game says otherwise)
const TYPES = {
  // ---- sources ----
  constant: { inputs: [], outputs: ['out'], params: { value: 0 } },
  toggle:   { inputs: [], outputs: ['out'], params: { value: 0 } },
  slider:   { inputs: [], outputs: ['out'], params: { value: 0 } },

  // ---- routing ----
  data_router_2: { inputs: ['in'], outputs: ['a', 'b'], params: {} },
  data_router_4: { inputs: ['in'], outputs: ['a', 'b', 'c', 'd'], params: {} },
  // game: "Sign Splitter" (internal JoystickSplitter). Both outputs positive.
  sign_splitter: { inputs: ['in'], outputs: ['pos', 'neg'], params: {} },
  // game: "Data Redirector 3" (SignalRouter3), selector 0..1 picks A/B/C.
  // Nearest-setpoint (0, 0.5, 1) selection comes from aupbuilder's tooltip — unconfirmed in-game.
  data_redirector_3: { inputs: ['sel', 'a', 'b', 'c'], outputs: ['out'], params: {} },
  // game: routes 1 of 5 inputs by pressed channel button; modelled as a 0..4 channel input.
  data_hub: { inputs: ['channel', 'i0', 'i1', 'i2', 'i3', 'i4'], outputs: ['out'], params: {} },
  // game: Datameter — displays its input and passes it through.
  datameter: { inputs: ['in'], outputs: ['out'], params: {} },

  // ---- logic ----
  // The game has AND / OR / XOR / NOT only — there is no NOR part (build it as NOT(OR)).
  // Truthiness: non-zero = true. UNCONFIRMED — the game may use >= 0.5 like Logic Value.
  not: { inputs: ['in'], outputs: ['out'], params: {} },
  and: { inputs: ['a', 'b'], outputs: ['out'], params: {} },
  or:  { inputs: ['a', 'b'], outputs: ['out'], params: {} },
  xor: { inputs: ['a', 'b'], outputs: ['out'], params: {} },
  logic_value: { inputs: ['in'], outputs: ['out'], params: {} }, // 1 if in >= 0.5
  simple_threshold: { inputs: ['in'], outputs: ['out'], params: { threshold: 0.5 } },
  // game: "True input port. If unconnected, defaults to 1. False ... defaults to 0."
  // op encoding is aupbuilder's (0 =, 1 ≠, 2 <, 3 >, 4 ≤, 5 ≥). The game's own mode byte
  // orders 3/4 the other way round (3 Less Equal, 4 Greater); the blueprint generator maps it.
  condition: { inputs: ['a', 'b', 'true', 'false'], outputs: ['out'], params: { op: 0 }, defaults: { true: 1, false: 0 } },

  // ---- arithmetic ----
  adder:      { inputs: ['a', 'b'], outputs: ['out'], params: {} },
  subtractor: { inputs: ['a', 'b'], outputs: ['out'], params: {} },
  multiplier: { inputs: ['a', 'b'], outputs: ['out'], params: {} },
  divider:    { inputs: ['a', 'b'], outputs: ['out'], params: {} },
  mod:        { inputs: ['a', 'b'], outputs: ['out'], params: {} },
  power:      { inputs: ['a', 'b'], outputs: ['out'], params: {} },
  max:        { inputs: ['a', 'b'], outputs: ['out'], params: {} },
  min:        { inputs: ['a', 'b'], outputs: ['out'], params: {} },
  abs:        { inputs: ['in'], outputs: ['out'], params: {} },
  sqrt:       { inputs: ['in'], outputs: ['out'], params: {} },
  exp:        { inputs: ['in'], outputs: ['out'], params: {} },
  log:        { inputs: ['in'], outputs: ['out'], params: {} },
  // 0 round, 1 floor, 2 ceil. The game's mode byte is 0 floor, 1 round, 2 ceil; the generator maps it.
  round:      { inputs: ['in'], outputs: ['out'], params: { mode: 0 } },
  // game: the output is clamped to the output range (SCTick_Remapper)
  remapper:   { inputs: ['in'], outputs: ['out'], params: { in_min: 0, in_max: 1, out_min: 0, out_max: 1 } },
  // game: "Addition Array" — sum of all connected inputs (7).
  sum: { inputs: ['a', 'b', 'c', 'd', 'e', 'f', 'g'], outputs: ['out'], params: {} },
  // game: Fader — "Multiplies input signal by fader value (0.0 - 1.0). If unconnected, defaults to 1."
  fader: { inputs: ['in'], outputs: ['out'], params: { value: 1 }, defaults: { in: 1 } },

  // ---- trig (radians, all game-confirmed) ----
  sin:  { inputs: ['in'], outputs: ['out'], params: {} },
  cos:  { inputs: ['in'], outputs: ['out'], params: {} },
  tan:  { inputs: ['in'], outputs: ['out'], params: {} },
  asin: { inputs: ['in'], outputs: ['out'], params: {} },
  acos: { inputs: ['in'], outputs: ['out'], params: {} },
  atan: { inputs: ['in'], outputs: ['out'], params: {} },
  atan2: { inputs: ['y', 'x'], outputs: ['out'], params: {} },
  sinh: { inputs: ['in'], outputs: ['out'], params: {} },
  cosh: { inputs: ['in'], outputs: ['out'], params: {} },
  tanh: { inputs: ['in'], outputs: ['out'], params: {} },

  // ---- stateful ----
  accumulator:    { inputs: ['in', 'reset'], outputs: ['out'], params: { mode: 0 } }, // 0 continuous, 1 pulse
  memory:         { inputs: ['value', 'set'], outputs: ['out'], params: { mode: 0 } },
  delay:          { inputs: ['in'], outputs: ['out'], params: { ticks: 1 } },
  // game (SCTick_Differentiator): every `interval` ticks it outputs the input minus the input at its
  // previous update, and holds that output in between. No division. interval is one of DIFF_INTERVALS.
  differentiator: { inputs: ['in'], outputs: ['out'], params: { interval: 1, simulate: 0 } },
  // game: outputs 0 until `ticks` game ticks have passed after entering Fly Mode, then passes input.
  // Its knob has 60 positions: ticks 0..59.
  initializer:    { inputs: ['in'], outputs: ['out'], params: { ticks: 10 } },
};

/* =========================================================================
   Game parts beyond pure logic: controls, sensors, displays, actuators,
   power, video and plasma.

   Port lists follow the game's own port order (Localization.csv,
   SC_<Part>_Port0..N), so port i here is the game's Port i. Prefixes:
     in / out     data ports (one tick per component, like everything else)
     pw           power port (undirected; joins a power network)
     vin / vout   video ports (carry 1 while the source is live)
     plin / plout plasma ports (carry the plasma level)

   Not in the game files: P/s figures, generation and battery capacity are
   stored in stripped asset data the tools can't decode, so they are block
   parameters. Copy the real figures from each part's in-game tooltip.
   ========================================================================= */
const DEFAULT_POWER_PS = 10;     // consumer draw, P/s (placeholder; set per block)
const DEFAULT_GEN_PS = 20;       // generator output, P/s (placeholder)
const DEFAULT_CAPACITY = 1000;   // battery capacity, Units (placeholder)

// behaviour, demand: how the part draws power ('constant' | 'proportional' to |input 0|,
// 'nonzero' while input 0 ≠ 0, 'active' while input 0 ≥ 0.5, 'change' on the tick input 0 changes)
const GAME_PARTS = {
  // ---- controls ----
  button:           ['Button', 'control', ['out out'], { bools: ['out'] }],
  small_button:     ['SmallButton', 'control', ['out out'], { bools: ['out'] }],
  switch:           ['Switch', 'control', ['out out'], { bools: ['out'] }],
  small_switch:     ['SmallSwitch', 'control', ['out out'], { bools: ['out'] }],
  stick_switch:     ['StickSwitch', 'control', ['out out'], { bools: ['out'] }],
  tnt_controller:   ['TNTController', 'control', ['out out'], { bools: ['out'] }],
  lever_vertical:   ['LeverVertical', 'control', ['out out']],
  lever_vertical_half: ['LeverVerticalHalf', 'control', ['out out']],
  lever_horizontal: ['LeverHorizontal', 'control', ['out out']],
  small_knob:       ['SmallKnob', 'control', ['out out']],
  joystick_horizontal: ['JoystickHorizontal', 'control', ['out horizontal']],
  joystick_vertical:   ['JoystickVertical', 'control', ['out vertical']],
  joystick_2d:      ['Joystick2D', 'control', ['out horizontal', 'out vertical']],
  joystick_3d:      ['Joystick3D', 'control', ['out yaw', 'out pitch', 'out roll']],

  // ---- sensors (the reading is a parameter you set) ----
  accelerometer:    ['Accelerometer', 'sensor', ['out acceleration']],
  aerometer:        ['Aerometer', 'sensor', ['out aerodynamics']],
  altimeter:        ['Altimeter', 'sensor', ['out height']],
  atmometer:        ['Atmometer', 'sensor', ['out density']],
  axis_rotometer:   ['AxisRotometer', 'sensor', ['out angular_velocity']],
  distance_meter:   ['DistanceMeter', 'sensor', ['out distance']],
  gravitymeter:     ['Gravitymeter', 'sensor', ['out gravity']],
  inclinometer:     ['Inclinometer', 'sensor', ['out angle']],
  massmeter:        ['Massmeter', 'sensor', ['out mass']],
  rotometer:        ['Rotometer', 'sensor', ['out rotation']],
  thermometer:      ['Thermometer', 'sensor', ['out temperature']],
  thermoscan:       ['Thermoscan', 'sensor', ['out temperature']],
  trajectory_curvature_meter: ['TrajectoryCurvatureMeter', 'sensor', ['out angle']],
  velocity_meter:   ['VelocityMeter', 'sensor', ['out velocity']],
  windmeter:        ['Windmeter', 'sensor', ['out wind_speed']],
  blue_tank:        ['BlueTank', 'sensor', ['out fuel']],
  green_tank:       ['GreenTank', 'sensor', ['out fuel']],
  long_range_distance_meter: ['LongRangeDistanceMeter', 'sensor', ['out distance', 'pw power'], { demand: 'constant' }],
  magnetometer:     ['Magnetometer', 'sensor', ['out activity', 'pw power'], { demand: 'constant' }],
  gyro_line:        ['GyroLine', 'sensor', ['out pitch', 'out roll', 'pw power'], { demand: 'constant' }],
  space_gps:        ['SpaceGPS', 'sensor', ['out distance', 'out longitude', 'out latitude', 'pw power'], { demand: 'constant' }],
  space_scanner:    ['SpaceScanner', 'sensor', ['in cone', 'out distance', 'pw power'], { demand: 'constant' }],
  fuel_analyzer:    ['FuelAnalyzer', 'sensor', ['in value', 'out performance', 'out stability', 'pw power'], { demand: 'constant' }],
  red_tank:         ['RedTank', 'red_tank', ['out fuel', 'out cooling', 'pw power'], { demand: 'constant' }],

  // ---- displays and indicators ----
  arc_90_meter:     ['Arc90Meter', 'display', ['in in']],
  arc_270_meter:    ['Arc270Meter', 'display', ['in in']],
  horizontal_meter: ['HorizontalMeter', 'display', ['in in']],
  vertical_meter:   ['VerticalMeter', 'display', ['in in']],
  large_datameter:  ['LargeDatameter', 'passthrough', ['in in', 'out out']],
  beeper:           ['Beeper', 'display', ['in in']],
  speaker:          ['Speaker', 'display', ['in in']],
  led_text:         ['LEDText', 'threshold_light', ['in in']],
  red_alert_light:  ['RedAlertLight', 'red_alert', ['in in']],
  colored_light_controller: ['ColoredLightController', 'display', ['in red', 'in green', 'in blue']],
  braking_point_system: ['BrakingPointSystem', 'bps', ['in distance', 'in velocity', 'in acceleration', 'out indicator']],
  eta_system:       ['ETASystem', 'eta', ['in distance', 'in velocity', 'in acceleration', 'out indicator']],

  // ---- thrusters, fans and other actuators ----
  small_electric_thruster:  ['SmallElectricThruster', 'thruster', ['in throttle', 'pw power'], { demand: 'proportional' }],
  medium_electric_thruster: ['MediumElectricThruster', 'thruster', ['in throttle', 'pw power'], { demand: 'proportional' }],
  large_electric_thruster:  ['LargeElectricThruster', 'thruster', ['in throttle', 'pw power'], { demand: 'proportional' }],
  electric_lift_thruster:   ['ElectricLiftThruster', 'thruster', ['in throttle', 'pw power'], { demand: 'proportional' }],
  bidirectional_maneuvering_thruster: ['BidirectionalElectricManeuveringThruster', 'thruster', ['in force', 'pw power'], { demand: 'proportional', signed: true }],
  small_maneuvering_thruster:  ['SmallManeuveringThruster', 'thruster', ['in throttle', 'pw power'], { demand: 'proportional' }],
  medium_maneuvering_thruster: ['MediumManeuveringThruster', 'thruster', ['in throttle', 'pw power'], { demand: 'proportional' }],
  large_maneuvering_thruster:  ['LargeManeuveringThruster', 'thruster', ['in throttle', 'pw power'], { demand: 'proportional' }],
  small_fuel_thruster:  ['SmallFuelThruster', 'thruster', ['in throttle', 'pw power'], { demand: 'nonzero' }],
  medium_fuel_thruster: ['MediumFuelThruster', 'thruster', ['in throttle', 'pw power'], { demand: 'nonzero' }],
  large_fuel_thruster:  ['LargeFuelThruster', 'thruster', ['in throttle', 'pw power'], { demand: 'nonzero' }],
  small_solid_fuel_thruster: ['SmallSolidFuelThruster', 'consumer', ['pw power'], { demand: 'constant' }],
  atmospheric_thruster: ['AtmosphericThruster', 'thruster', ['in throttle', 'pw power'], { demand: 'proportional' }],
  atmospheric_fan:      ['AtmosphericFan', 'thruster', ['in speed', 'pw power'], { demand: 'proportional', signed: true }],
  atmospheric_lift_fan: ['AtmosphericLiftFan', 'thruster', ['in speed', 'pw power'], { demand: 'proportional' }],
  ducted_fan:           ['DuctedFan', 'thruster', ['in speed', 'pw power', 'in rotation'], { demand: 'proportional', signed: true }],
  ballast:              ['Ballast', 'thruster', ['in buoyancy', 'pw power'], { demand: 'proportional' }],
  rcs_controller:       ['GimbalController', 'consumer', ['in yaw', 'in pitch', 'in roll', 'pw power'], { demand: 'constant' }],
  floodlight:           ['Floodlight', 'consumer', ['in intensity', 'in horizontal', 'in vertical', 'pw power'], { demand: 'proportional' }],
  rimcore_turbo:        ['RimcoreTurbo', 'consumer', ['in on', 'pw power'], { demand: 'active' }],
  lava_sucker:          ['LavaSucker', 'consumer', ['in on', 'in length', 'pw power'], { demand: 'active' }],
  extendable_damper:    ['ExtendableDamper', 'consumer', ['in extension', 'pw power'], { demand: 'change' }],
  pipe_electric_valve:     ['PipeElectricValve', 'consumer', ['in open', 'pw power'], { demand: 'change' }],
  nanopipe_electric_valve: ['NanopipeElectricValve', 'consumer', ['in open', 'pw power'], { demand: 'change' }],
  small_gate:         ['SmallGate', 'consumer', ['in state', 'pw power'], { demand: 'change' }],
  medium_gate:        ['MediumGate', 'consumer', ['in state', 'pw power'], { demand: 'change' }],
  large_gate:         ['LargeGate', 'consumer', ['in state', 'pw power'], { demand: 'change' }],
  small_nanogate:     ['SmallNanogate', 'consumer', ['in state', 'pw power'], { demand: 'change' }],
  medium_nanogate:    ['MediumNanogate', 'consumer', ['in state', 'pw power'], { demand: 'change' }],
  large_nanogate:     ['LargeNanogate', 'consumer', ['in state', 'pw power'], { demand: 'change' }],
  personnel_gate:     ['PersonnelGate', 'consumer', ['in state', 'pw power'], { demand: 'change' }],
  personnel_nanogate: ['PersonnelNanogate', 'consumer', ['in state', 'pw power'], { demand: 'change' }],
  ramp_gate:          ['RampGate', 'consumer', ['in state', 'pw power'], { demand: 'change' }],
  ramp_nanogate:      ['RampNanogate', 'consumer', ['in state', 'pw power'], { demand: 'change' }],
  radar:              ['Radar', 'consumer', ['pw power'], { demand: 'constant' }],
  green_trench_pump:  ['GreenTrenchPump', 'consumer', ['pw power'], { demand: 'constant' }],
  ice_cream_freezer:  ['IceCreamFreezer', 'consumer', ['pw power'], { demand: 'constant' }],
  outcast_polar_anchor: ['OutcastPolarAnchor', 'consumer', ['pw power'], { demand: 'constant' }],
  bomb_c4:            ['BombC4', 'trigger', ['in trigger'], { latch: 'DETONATED' }],
  tnt_box:            ['TNTBox', 'trigger', ['in trigger'], { latch: 'DETONATED' }],
  clima_bomb:         ['ClimaBomb', 'trigger', ['in trigger'], { latch: 'DECOUPLED' }],
  decoupler_small:    ['DecouplerQuarter', 'trigger', ['in trigger'], { latch: 'DECOUPLED' }],

  // ---- power ----
  small_disposable_battery:    ['SmallDisposableBattery', 'battery', ['pw power'], { rechargeable: false }],
  medium_disposable_battery:   ['MediumDisposableBattery', 'battery', ['pw power', 'out level'], { rechargeable: false }],
  large_disposable_battery:    ['LargeDisposableBattery', 'battery', ['pw power', 'out level'], { rechargeable: false }],
  small_rechargeable_battery:  ['SmallRechargeableBattery', 'battery', ['pw power'], { rechargeable: true }],
  medium_rechargeable_battery: ['MediumRechargeableBattery', 'battery', ['pw power', 'out level'], { rechargeable: true }],
  large_rechargeable_battery:  ['LargeRechargeableBattery', 'battery', ['pw power', 'out level'], { rechargeable: true }],
  solar_panel:        ['SolarPanel', 'generator', ['pw a', 'pw b']],
  autohemisphere_solar_panel: ['AutohemisphereSolarPanel', 'generator', ['pw power']],
  dynamo_box:         ['DynamoBox', 'generator', ['pw power']],
  power_router:       ['PowerRouter', 'power_router', ['pw a', 'pw b', 'pw c', 'pw d']],
  large_power_router: ['LargePowerRouter', 'power_router', ['pw a', 'pw b', 'pw c', 'pw d', 'pw e', 'pw f', 'pw g', 'pw h']],
  fuse_box:           ['FuseBox', 'fuse', ['pw a', 'pw b'], { bools: ['on'] }],
  power_blocker:      ['PowerBlocker', 'blocker', ['in block', 'pw a', 'pw b']],
  power_generation_meter: ['PowerGenerationMeter', 'power_meter', ['out generation', 'pw power'], { measure: 'gen' }],
  power_usage_meter:      ['PowerUsageMeter', 'power_meter', ['out usage', 'pw power'], { measure: 'use' }],

  // ---- video ----
  camera:              ['Camera', 'camera', ['vout video', 'pw power'], { demand: 'constant' }],
  night_vision_camera: ['NightVisionCamera', 'camera', ['vout video', 'pw power'], { demand: 'constant' }],
  zoom_camera:         ['ZoomCamera', 'camera', ['vout video', 'in zoom', 'pw power'], { demand: 'constant' }],
  rotational_telescope: ['RotationalTelescope', 'camera', ['vout video', 'in horizontal', 'in vertical', 'in roll', 'in zoom', 'pw power'], { demand: 'constant' }],
  camera_overlay:      ['CameraOverlay', 'camera', ['vout video', 'in row_1', 'in row_2', 'in row_3', 'in row_4', 'pw power'], { demand: 'constant' }],
  monitor_crt:         ['MonitorCRT', 'monitor', ['vin video', 'pw power'], { demand: 'constant' }],
  monitor_small_lcd:   ['MonitorSmallLCD', 'monitor', ['vin primary', 'vin secondary', 'pw power'], { demand: 'constant' }],
  monitor_medium_lcd:  ['MonitorMediumLCD', 'monitor', ['vin primary', 'vin secondary', 'pw power'], { demand: 'constant' }],
  monitor_large_lcd:   ['MonitorLargeLCD', 'monitor', ['vin primary', 'vin secondary', 'pw power'], { demand: 'constant' }],
  monitor_small_hologram:  ['MonitorSmallHologram', 'monitor', ['vin primary', 'vin secondary', 'pw power'], { demand: 'constant' }],
  monitor_medium_hologram: ['MonitorMediumHologram', 'monitor', ['vin primary', 'vin secondary', 'pw power'], { demand: 'constant' }],
  monitor_large_hologram:  ['MonitorLargeHologram', 'monitor', ['vin primary', 'vin secondary', 'pw power'], { demand: 'constant' }],

  // ---- plasma ----
  small_plasma_generator: ['SmallPlasmaGenerator', 'plasma_gen', ['in speed', 'pw power', 'plout plasma'], { demand: 'proportional' }],
  solar_shield_generator: ['SolarShieldGenerator', 'shield', ['plin plasma', 'in radius', 'out max_heat']],
  wind_shield_generator:  ['WindShieldGenerator', 'shield', ['plin plasma', 'in radius', 'out max_wind']],

  // ---- wireless (one bidirectional port in the game: wired in = transmit, out = receive) ----
  wireless_transmitter: ['WirelessTransmitter', 'wireless', ['in tx', 'out rx'], { sharedPort: { rx: 'tx' } }],
};

const PORT_KIND = { in: 'data', out: 'data', pw: 'power', vin: 'video', vout: 'video', plin: 'plasma', plout: 'plasma' };
const IS_INPUT = { in: true, vin: true, plin: true };
const IS_OUTPUT = { out: true, vout: true, plout: true };

for (const [type_id, [game, behavior, portSpecs, opts = {}]] of Object.entries(GAME_PARTS)) {
  const ports = portSpecs.map((spec) => { const [pre, name] = spec.split(' '); return { pre, name, kind: PORT_KIND[pre] }; });
  const def = {
    game, behavior,
    order: ports.map((pt) => pt.name).filter((n) => !(opts.sharedPort && opts.sharedPort[n])), // game port order
    sharedPort: opts.sharedPort || null,         // our port -> the game port it is half of
    inputs: ports.filter((pt) => IS_INPUT[pt.pre]).map((pt) => pt.name),
    outputs: ports.filter((pt) => IS_OUTPUT[pt.pre]).map((pt) => pt.name),
    power: ports.filter((pt) => pt.pre === 'pw').map((pt) => pt.name),
    kinds: Object.fromEntries(ports.filter((pt) => pt.kind !== 'data').map((pt) => [pt.name, pt.kind])),
    bools: opts.bools || [],
    demand: opts.demand || null,
    opts,
    params: {},
  };
  if (behavior === 'control' || behavior === 'sensor' || behavior === 'red_tank' || behavior === 'shield') {
    for (const o of def.outputs) if (!(behavior === 'red_tank' && o === 'cooling')) def.params[o] = 0;
  }
  if (behavior === 'fuse') Object.assign(def.params, { on: 1, limit_ps: 150 });
  if (behavior === 'battery') Object.assign(def.params, { capacity: DEFAULT_CAPACITY, charge: DEFAULT_CAPACITY });
  if (behavior === 'eta') def.params.mode = 2;   // knob: 0 time to the braking point, 1 braking time, 2 whole trip
  if (behavior === 'generator') def.params.gen_ps = DEFAULT_GEN_PS;
  if (behavior === 'wireless') def.params.channel = 1;
  if (def.demand) def.params.power_ps = DEFAULT_POWER_PS;
  TYPES[type_id] = def;
}

// math blocks the game also has
for (const fn of ['asinh', 'acosh', 'atanh']) TYPES[fn] = { inputs: ['in'], outputs: ['out'], params: {} };

// Game part name (Localization key SC_<name>) for the logic/math blocks defined above.
// `order` is the game's port order where our port names differ from it.
const LOGIC_GAME_PARTS = {
  constant: ['Constant'], toggle: ['Switch'], slider: ['LeverVertical'],
  data_router_2: ['Router2', ['in', 'a', 'b']], data_router_4: ['Router4', ['in', 'a', 'b', 'c', 'd']],
  sign_splitter: ['JoystickSplitter', ['in', 'neg', 'pos']], data_redirector_3: ['SignalRouter3', ['a', 'b', 'c', 'sel', 'out']],
  data_hub: ['DataHub', ['i0', 'i1', 'i2', 'i3', 'i4', 'out']], datameter: ['Datameter', ['in', 'out']],
  not: ['LogicGateNot', ['in', 'out']], and: ['LogicGateAnd', ['a', 'b', 'out']], or: ['LogicGateOr', ['a', 'b', 'out']],
  xor: ['LogicGateXor', ['a', 'b', 'out']], logic_value: ['LogicValue', ['in', 'out']],
  simple_threshold: ['SimpleThreshold', ['in', 'out']], condition: ['Condition', ['a', 'b', 'true', 'false', 'out']],
  adder: ['Adder', ['a', 'b', 'out']], subtractor: ['Subtractor', ['a', 'b', 'out']], multiplier: ['Multiplier', ['a', 'b', 'out']],
  divider: ['Divider', ['a', 'b', 'out']], mod: ['Mod', ['a', 'b', 'out']], power: ['Pow', ['a', 'b', 'out']],
  max: ['Maximum', ['a', 'b', 'out']], min: ['Minimum', ['a', 'b', 'out']], abs: ['Abs', ['in', 'out']], sqrt: ['Sqrt', ['in', 'out']],
  exp: ['Exp', ['in', 'out']], log: ['Log', ['in', 'out']], round: ['Round', ['in', 'out']], remapper: ['Remapper', ['in', 'out']],
  sum: ['AdditionArray', ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'out']], fader: ['Fader', ['in', 'out']],
  sin: ['Sin', ['in', 'out']], cos: ['Cos', ['in', 'out']], tan: ['Tan', ['in', 'out']],
  asin: ['Asin', ['in', 'out']], acos: ['Acos', ['in', 'out']], atan: ['Atan', ['in', 'out']], atan2: ['Atan2', ['y', 'x', 'out']],
  sinh: ['Sinh', ['in', 'out']], cosh: ['Cosh', ['in', 'out']], tanh: ['Tanh', ['in', 'out']],
  asinh: ['Asinh', ['in', 'out']], acosh: ['Acosh', ['in', 'out']], atanh: ['Atanh', ['in', 'out']],
  accumulator: ['Accumulator', ['in', 'reset', 'out']], memory: ['Memory', ['value', 'set', 'out']],
  delay: ['Delay', ['in', 'out']], differentiator: ['Differentiator', ['in', 'out']], initializer: ['Initializer', ['in', 'out']],
};
for (const [type_id, [game, order]] of Object.entries(LOGIC_GAME_PARTS)) {
  TYPES[type_id].game = game;
  if (order) TYPES[type_id].order = order;
}

const isPowerPort = (type_id, port) => !!(TYPES[type_id].power && TYPES[type_id].power.includes(port));
const portKind = (type_id, port) => (isPowerPort(type_id, port) ? 'power' : (TYPES[type_id].kinds && TYPES[type_id].kinds[port]) || 'data');

// The game's Condition "Equal": relative tolerance 1e-6, absolute floor 2^-20 (SCTick_Condition).
const approxEqual = (a, b) => Math.abs(a - b) < Math.max(1e-6 * Math.max(Math.abs(a), Math.abs(b)), 2 ** -20);

function opCompare(op, a, b) {
  switch (op) {
    case 0: return approxEqual(a, b);
    case 1: return !approxEqual(a, b);
    case 2: return a < b;
    case 3: return a > b;
    case 4: return a <= b;
    case 5: return a >= b;
    default: return false;
  }
}

const clampTicks = (n) => Math.max(1, Math.min(60, Math.round(n || 1)));
const initializerTicks = (n) => Math.max(0, Math.min(59, Math.round(n || 0)));
// Nearest interval the game's Differentiator knob offers (ties go to the shorter one).
const snapInterval = (n) => DIFF_INTERVALS.reduce((best, v) => (Math.abs(v - n) < Math.abs(best - n) ? v : best));
const truthy = (x) => x !== 0;

class CircuitEngine {
  constructor(diagram) {
    this.instances = new Map();
    for (const inst of diagram.instances) {
      const type = TYPES[inst.type_id];
      if (!type) throw new Error(`Unknown block type_id "${inst.type_id}" on node "${inst.id}"`);
      const params = { ...type.params, ...(inst.parameters || {}) };
      this.instances.set(inst.id, {
        id: inst.id,
        type_id: inst.type_id,
        params,
        stateful: STATEFUL.has(inst.type_id),
        state: this._initState(inst.type_id, params),
        outputs: Object.fromEntries(type.outputs.map((p) => [p, 0])),
      });
    }
    this.edges = diagram.edges.map((e) => ({ ...e }));
    this.incoming = new Map();
    this.powerEdges = []; // undirected power cables
    for (const id of this.instances.keys()) this.incoming.set(id, {});
    for (const e of this.edges) {
      if (!this.instances.has(e.from_instance)) throw new Error(`Edge sources unknown instance "${e.from_instance}"`);
      if (!this.instances.has(e.to_instance)) throw new Error(`Edge targets unknown instance "${e.to_instance}"`);
      const fromType = this.instances.get(e.from_instance).type_id;
      const toType = this.instances.get(e.to_instance).type_id;
      const fk = portKind(fromType, e.from_port), tk = portKind(toType, e.to_port);
      if (fk !== tk) throw new Error(`Cannot wire ${fk} port ${e.from_instance}.${e.from_port} to ${tk} port ${e.to_instance}.${e.to_port}`);
      if (fk === 'power') { this.powerEdges.push(e); continue; }
      this.incoming.get(e.to_instance)[e.to_port] = { from_instance: e.from_instance, from_port: e.from_port };
    }
    this.tick = 0;
    this.powered = new Map();  // instance id -> powered this tick (blocks with power ports only)
    this.nets = [];            // last power solve, for inspection
    this.status = new Map();   // instance id -> short human-readable state, for the UI
  }

  // ---- power ----------------------------------------------------------------
  // Each tick, before any block computes: join power ports into networks, then
  // decide per network whether generation + battery charge covers demand.
  // Demand and switching inputs are read from last tick's outputs, like any data.
  _demandOf(inst) {
    const t = TYPES[inst.type_id];
    if (!t.demand) return 0;
    const ps = Math.max(0, inst.params.power_ps || 0);
    const x = t.inputs.length ? this._readPort(inst.id, t.inputs[0]) : 0;
    switch (t.demand) {
      case 'constant': return ps;
      case 'proportional': return ps * Math.min(1, Math.abs(x));
      case 'nonzero': return x !== 0 ? ps : 0;
      case 'active': return x >= 0.5 ? ps : 0;
      case 'change': return x !== (inst.state.prevDemandIn ?? 0) ? ps : 0;
      default: return 0;
    }
  }

  _solvePower() {
    const parent = new Map();
    const key = (id, port) => id + '\u0000' + port;
    const find = (k) => { while (parent.get(k) !== k) { parent.set(k, parent.get(parent.get(k))); k = parent.get(k); } return k; };
    const union = (a, b) => { const ra = find(a), rb = find(b); if (ra !== rb) parent.set(ra, rb); };
    for (const inst of this.instances.values()) for (const pt of TYPES[inst.type_id].power || []) parent.set(key(inst.id, pt), key(inst.id, pt));
    if (parent.size === 0) return;
    for (const e of this.powerEdges) union(key(e.from_instance, e.from_port), key(e.to_instance, e.to_port));
    for (const inst of this.instances.values()) {
      const t = TYPES[inst.type_id];
      if (!t.power || t.power.length < 2) continue;
      const joined = t.behavior === 'fuse' ? !!inst.params.on
        : t.behavior === 'blocker' ? this._readPort(inst.id, 'block') < 0.5
        : true; // routers and two-port solar panels are one junction
      if (joined) for (let i = 1; i < t.power.length; i++) union(key(inst.id, t.power[0]), key(inst.id, t.power[i]));
    }

    const nets = new Map();
    const netOf = (inst) => {
      const r = find(key(inst.id, TYPES[inst.type_id].power[0]));
      if (!nets.has(r)) nets.set(r, { gen: 0, demand: 0, batteries: [], consumers: [], members: [] });
      return nets.get(r);
    };
    for (const inst of this.instances.values()) {
      const t = TYPES[inst.type_id];
      if (!t.power || !t.power.length) continue;
      const net = netOf(inst);
      net.members.push(inst);
      inst.state.net = net;
      if (t.behavior === 'generator') net.gen += Math.max(0, inst.params.gen_ps || 0);
      else if (t.behavior === 'battery') net.batteries.push(inst);
      else if (t.demand) { const d = this._demandOf(inst); inst.state.demandNow = d; net.demand += d; net.consumers.push(inst); }
    }

    this.powered = new Map();
    for (const net of nets.values()) {
      const charge = net.batteries.reduce((a, b) => a + Math.max(0, b.params.charge), 0);
      const hasSource = net.gen > 0 || charge > 0;
      const deficitPerTick = Math.max(0, net.demand - net.gen) / 60;
      net.ok = hasSource && (deficitPerTick === 0 || charge >= deficitPerTick);
      if (net.ok && deficitPerTick > 0) {
        let need = deficitPerTick;   // draw from batteries in order until covered
        for (const b of net.batteries) { const take = Math.min(need, Math.max(0, b.params.charge)); b.params.charge -= take; need -= take; }
      } else if (net.gen > net.demand) {
        let spare = (net.gen - net.demand) / 60; // surplus tops up rechargeable batteries
        for (const b of net.batteries) {
          if (!TYPES[b.type_id].opts.rechargeable) continue;
          const room = Math.max(0, b.params.capacity - b.params.charge);
          const put = Math.min(room, spare); b.params.charge += put; spare -= put;
        }
      }
      net.usage = net.ok ? net.demand : 0;
      for (const m of net.members) this.powered.set(m.id, net.ok);
    }
    // Fuse boxes trip (and stay off) when the circuit they join draws more than their limit.
    for (const inst of this.instances.values()) {
      if (TYPES[inst.type_id].behavior !== 'fuse' || !inst.params.on) continue;
      if (inst.state.net && inst.state.net.demand > inst.params.limit_ps) inst.params.on = 0;
    }
    this.nets = [...nets.values()];
  }

  _isPowered(inst) {
    const t = TYPES[inst.type_id];
    if (!t.power || !t.power.length) return true;
    return !!this.powered.get(inst.id);
  }

  // ---- wireless: one transmitter per channel, any number of receivers ----
  _solveWireless() {
    this.channels = new Map();
    for (const inst of this.instances.values()) {
      if (TYPES[inst.type_id].behavior !== 'wireless' || !this.incoming.get(inst.id).tx) continue;
      const ch = inst.params.channel;
      const c = this.channels.get(ch) || { senders: [] };
      c.senders.push(inst);
      this.channels.set(ch, c);
    }
  }

  _initState(type_id, params) {
    switch (type_id) {
      case 'accumulator': return { total: 0, prevReset: 0 };
      case 'memory': return { stored: 0, prevSet: 0 };
      case 'delay': {
        const n = clampTicks(params.ticks) + (DELAY_ADDS_TO_COMPONENT_TICK ? 0 : -1);
        return { buf: new Array(Math.max(0, n)).fill(0) };
      }
      case 'differentiator': return { last: 0, lastTick: 0, out: 0 };
      default: return {};
    }
  }

  // Value an input port currently sees: its driver's output as of the end of the last tick.
  _readPort(instId, portName) {
    const driver = this.incoming.get(instId)[portName];
    if (!driver) {
      const defaults = TYPES[this.instances.get(instId).type_id].defaults;
      return (defaults && defaults[portName]) ?? 0;
    }
    return this.instances.get(driver.from_instance).outputs[driver.from_port] ?? 0;
  }

  _step() {
    this._solvePower();
    this._solveWireless();
    // Compute every block's next outputs from the current (last-tick) outputs...
    const next = new Map();
    for (const inst of this.instances.values()) next.set(inst.id, this._compute(inst));
    // ...then commit them all at once.
    for (const [id, outs] of next) this.instances.get(id).outputs = outs;
    this.tick++;
  }

  _compute(inst) {
    const p = inst.params;
    const s = inst.state;
    const v = (name) => this._readPort(inst.id, name);
    switch (inst.type_id) {
      case 'constant': return { out: p.value };
      case 'toggle':   return { out: p.value ? 1 : 0 };
      case 'slider':   return { out: p.value };

      case 'data_router_2': { const x = v('in'); return { a: x, b: x }; }
      case 'data_router_4': { const x = v('in'); return { a: x, b: x, c: x, d: x }; }
      case 'sign_splitter': { const x = v('in'); return { pos: Math.max(x, 0), neg: Math.max(-x, 0) }; }
      case 'data_redirector_3': {
        const sel = v('sel');
        const d0 = Math.abs(sel), d1 = Math.abs(sel - 0.5), d2 = Math.abs(sel - 1);
        return { out: (d0 <= d1 && d0 <= d2) ? v('a') : (d1 <= d2) ? v('b') : v('c') };
      }
      case 'data_hub': return { out: v('i' + Math.max(0, Math.min(4, Math.round(v('channel'))))) };
      case 'datameter': return { out: v('in') };

      case 'not': return { out: truthy(v('in')) ? 0 : 1 };
      case 'and': return { out: (truthy(v('a')) && truthy(v('b'))) ? 1 : 0 };
      case 'or':  return { out: (truthy(v('a')) || truthy(v('b'))) ? 1 : 0 };
      case 'xor': return { out: (truthy(v('a')) !== truthy(v('b'))) ? 1 : 0 };
      case 'logic_value': return { out: v('in') >= 0.5 ? 1 : 0 };
      case 'simple_threshold': return { out: v('in') >= p.threshold ? 1 : 0 };
      case 'condition': return { out: opCompare(p.op, v('a'), v('b')) ? v('true') : v('false') };

      case 'adder':      return { out: v('a') + v('b') };
      case 'subtractor': return { out: v('a') - v('b') };
      case 'multiplier': return { out: v('a') * v('b') };
      case 'divider':    return { out: v('b') === 0 ? 0 : v('a') / v('b') }; // game behaviour on /0 unconfirmed
      case 'mod':        return { out: v('b') === 0 ? 0 : v('a') % v('b') };
      case 'power':      return { out: Math.pow(v('a'), v('b')) };
      case 'max':        return { out: Math.max(v('a'), v('b')) };
      case 'min':        return { out: Math.min(v('a'), v('b')) };
      case 'abs':        return { out: Math.abs(v('in')) };
      case 'sqrt':       return { out: Math.sqrt(Math.max(0, v('in'))) };
      case 'exp':        return { out: Math.exp(v('in')) };
      case 'log':        { const x = v('in'); return { out: x > 0 ? Math.log(x) : 0 }; } // game: "must be > 0"
      case 'round': {
        const x = v('in');
        // game rounds halves away from zero: sign(x) * floor(|x| + 0.5)
        return { out: p.mode === 1 ? Math.floor(x) : p.mode === 2 ? Math.ceil(x) : Math.sign(x) * Math.floor(Math.abs(x) + 0.5) };
      }
      case 'remapper': {
        const x = v('in');
        const lo = Math.min(p.out_min, p.out_max), hi = Math.max(p.out_min, p.out_max);
        if (Math.abs(p.in_max - p.in_min) < 1e-9) return { out: x < p.in_min ? lo : hi }; // game's step for an empty range
        const t = Math.max(0, Math.min(1, (x - p.in_min) / (p.in_max - p.in_min)));
        return { out: p.out_min + t * (p.out_max - p.out_min) };
      }
      case 'sum': return { out: ['a', 'b', 'c', 'd', 'e', 'f', 'g'].reduce((acc, k) => acc + v(k), 0) };
      case 'fader': return { out: v('in') * Math.max(0, Math.min(1, p.value)) };

      case 'sin':  return { out: Math.sin(v('in')) };
      case 'cos':  return { out: Math.cos(v('in')) };
      case 'tan':  return { out: Math.tan(v('in')) };
      case 'asin': return { out: Math.asin(Math.max(-1, Math.min(1, v('in')))) };
      case 'acos': return { out: Math.acos(Math.max(-1, Math.min(1, v('in')))) };
      case 'atan': return { out: Math.atan(v('in')) };
      case 'atan2': return { out: Math.atan2(v('y'), v('x')) };
      case 'sinh': return { out: Math.sinh(v('in')) };
      case 'cosh': return { out: Math.cosh(v('in')) };
      case 'tanh': return { out: Math.tanh(v('in')) };

      case 'accumulator': {
        // "Adds the input value to its internal total and outputs the result."
        const r = v('reset');
        const resetting = p.mode === 1 ? (r >= 0.5 && s.prevReset < 0.5) : r >= 0.5;
        s.prevReset = r;
        s.total = resetting ? 0 : s.total + v('in');
        return { out: s.total };
      }
      case 'memory': {
        const set = v('set');
        const latch = p.mode === 1 ? (set >= 0.5 && s.prevSet < 0.5) : set >= 0.5;
        s.prevSet = set;
        if (latch) s.stored = v('value');
        return { out: s.stored };
      }
      case 'delay': {
        if (s.buf.length === 0) return { out: v('in') };
        s.buf.push(v('in'));
        return { out: s.buf.shift() };
      }
      case 'differentiator': {
        if (s.lastTick + snapInterval(p.interval) <= this.tick) {
          const x = v('in');
          s.out = x - s.last;
          s.last = x;
          s.lastTick = this.tick;
        }
        return { out: s.out };
      }
      case 'initializer': return { out: this.tick >= initializerTicks(p.ticks) ? v('in') : 0 };

      case 'asinh': return { out: Math.asinh(v('in')) };
      case 'acosh': return { out: Math.acosh(Math.max(1, v('in'))) };                       // game: "must be ≥ 1"
      case 'atanh': return { out: Math.atanh(Math.max(-1 + 1e-12, Math.min(1 - 1e-12, v('in')))) };

      default:
        if (TYPES[inst.type_id].behavior) return this._computeGamePart(inst, v);
        throw new Error('no handler for ' + inst.type_id);
    }
  }

  _computeGamePart(inst, v) {
    const t = TYPES[inst.type_id];
    const p = inst.params;
    const s = inst.state;
    const on = this._isPowered(inst);
    const zeros = () => Object.fromEntries(t.outputs.map((o) => [o, 0]));
    const say = (text) => this.status.set(inst.id, text);
    const fmtNum = (x) => (Math.abs(x) >= 1e5 ? x.toExponential(2) : String(Math.round(x * 1000) / 1000));
    const noPower = 'no power';
    let out;

    switch (t.behavior) {
      case 'control':
        out = Object.fromEntries(t.outputs.map((o) => [o, t.bools.includes(o) ? (p[o] ? 1 : 0) : p[o]]));
        break;
      case 'sensor':
        out = on ? Object.fromEntries(t.outputs.map((o) => [o, p[o]])) : zeros();
        if (t.power.length) say(on ? 'reading' : noPower);
        break;
      case 'red_tank':
        out = { fuel: on ? p.fuel : 0, cooling: on ? 1 : 0 }; // cooling fails without power
        say(on ? 'cooling' : 'NOT COOLING');
        break;
      case 'passthrough': out = { out: v('in') }; break;
      case 'display': say('shows ' + t.inputs.map((i) => fmtNum(v(i))).join(' / ')); out = {}; break;
      case 'threshold_light': say(v('in') >= 0.5 ? 'ON' : 'off'); out = {}; break;
      case 'red_alert': { const x = v('in'); say(x > 0.666 ? 'LIGHT + ALARM' : x > 0.333 ? 'LIGHT' : 'off'); out = {}; break; }
      case 'bps': {
        // Game code (SCTick_BrakingPointSystem), with v = |velocity| and a = |acceleration|:
        //   target = +1 below 0.0001 m/s; else −1 if a < 0.00001 m/s² or the distance is under 1 mm; else
        //   log2(distance / stopping distance v²/2a) / 6, clamped to ±1. So 0 means "stops exactly at the
        //   surface", and ±1 means a 64× margin either way (each 1/6 step is a doubling).
        // The output does not jump: each tick it moves BPS_EASE (≈ 0.139) of the way from its last value.
        const d = v('distance'), vel = Math.abs(v('velocity')), a = Math.abs(v('acceleration'));
        let target;
        if (vel < 1e-4) target = 1;
        else if (a < 1e-5 || d < 1e-3) target = -1;
        else target = Math.max(-1, Math.min(1, Math.log2(d / ((vel * vel) / (2 * a))) / 6));
        const prev = Math.max(-1, Math.min(1, s.indicator || 0));
        s.indicator = prev + (target - prev) * BPS_EASE;
        out = { indicator: s.indicator };
        break;
      }
      case 'eta': {
        // Game code (SCTick_ETASystem). The part is not in the shipped game: no SC_ETASystem prefab exists.
        // Despite its port text ("indicator 0..1"), it outputs a time in seconds, picked by its knob (`mode`).
        // With d = distance, v = velocity (signed) and A = |acceleration|, the stopping distance is S = v²/2A.
        //   S < d: it plans the fastest stop on the target, accelerating at A for t and then braking at A, where
        //          A·t² + 2v·t + (S − d) = 0 (the larger root). Mode 0 gives t (time left before braking must
        //          start), 1 gives t + v/A (the braking), and 2 or more gives 2t + v/A (the whole trip).
        //   S ≥ d: it cannot stop in time. Modes 1 and 2 give the time to impact, the first positive root of
        //          d = v·t + ½a·t², where a counts as braking (negative) when the speed fell since the last tick;
        //          mode 0 gives 0. With no acceleration at all this finds no root, and every mode gives 0.
        // The in-game readout shows the time as H:MM:SS (capped at 100 h): red on a collision course, else green.
        const san = (x) => (x > 1e20 || Number.isNaN(x) ? 0 : x);      // inputs above 1e20, or NaN, read as 0
        const minss = (a, b) => (a < b ? a : b), maxss = (a, b) => (a > b ? a : b);   // x86 rules: NaN → b
        const d = san(v('distance')), vel = san(v('velocity')), aIn = san(v('acceleration'));
        const A = Math.abs(aIn);
        const mode = Math.max(0, Math.round(p.mode || 0));
        const prevV = s.prevV || 0;
        s.prevV = vel;
        let first = 0, second = 0, collision = false;   // the job's two results; mode 2 adds them
        const S = (vel * vel) / (2 * A);
        if (S >= d) {
          const a = prevV > vel ? -aIn : aIn;
          const D = vel * vel + 2 * a * d;
          if (!(0 > D)) {
            const sq = Math.sqrt(D), r0 = (-vel - sq) / a, r1 = (sq - vel) / a;
            let hit = FLT_MAX;
            if (0 < r1) hit = minss(r1, hit);
            if (0 < r0) hit = minss(r0, hit);
            if (hit !== FLT_MAX) { second = hit; collision = true; }
          }
        } else {
          const b = 2 * vel, D = b * b - 4 * A * (S - d);
          if (!(0 > D)) {
            const sq = Math.sqrt(D), r1 = (sq - b) / (2 * A), r2 = (-b - sq) / (2 * A);
            const hi = Number.isNaN(r2) ? r1 : maxss(r1, r2), lo = Number.isNaN(r2) ? r1 : minss(r1, r2);
            const t = !(hi < 0) ? hi : lo;
            if (!(0 > t)) { first = t; second = (t * A + vel) / A; }
          }
        }
        const time = mode === 0 ? first : mode === 1 ? second : first + second;
        out = { indicator: maxss(minss(time, 1e20), -1e20) };
        const secs = Math.trunc(maxss(minss(time, 360000), 0));
        const pad = (n) => String(n).padStart(2, '0');
        say(`${Math.floor(secs / 3600)}:${pad(Math.floor(secs / 60) % 60)}:${pad(secs % 60)}${collision ? ' · COLLISION' : ''}`);
        break;
      }
      case 'thruster': {
        const x = v(t.inputs[0]);
        const level = on ? (t.opts.signed ? Math.max(-1, Math.min(1, x)) : Math.max(0, Math.min(1, x))) : 0;
        s.level = level;
        say(on ? `${Math.round(level * 100)}%` : noPower);
        out = {};
        break;
      }
      case 'consumer':
        say(on ? (t.inputs.length ? `on · ${fmtNum(v(t.inputs[0]))}` : 'on') : noPower);
        out = {};
        break;
      case 'trigger':
        if (v('trigger') >= 0.5) s.fired = true;
        say(s.fired ? t.opts.latch : 'armed');
        out = {};
        break;
      case 'battery':
        p.charge = Math.max(0, Math.min(p.capacity, p.charge));
        say(`${fmtNum(p.charge)} / ${fmtNum(p.capacity)} U`);
        out = t.outputs.includes('level') ? { level: p.charge } : {};
        break;
      case 'generator': say(`+${fmtNum(p.gen_ps)} P/s`); out = {}; break;
      case 'power_router': out = {}; break;
      case 'fuse': say(p.on ? 'closed' : 'TRIPPED'); out = {}; break;
      case 'blocker': say(v('block') >= 0.5 ? 'blocking' : 'passing'); out = {}; break;
      case 'power_meter': {
        const net = s.net;
        out = { [t.outputs[0]]: net ? (t.opts.measure === 'gen' ? net.gen : net.usage) : 0 };
        break;
      }
      case 'camera': out = { video: on ? 1 : 0 }; say(on ? 'live' : noPower); break;
      case 'monitor': {
        const sig = t.inputs.some((i) => v(i) > 0);
        say(!on ? noPower : sig ? 'showing video' : 'no signal');
        out = {};
        break;
      }
      case 'plasma_gen': {
        const x = Math.max(0, Math.min(1, v('speed')));
        out = { plasma: on ? x : 0 };
        say(on ? `plasma ${fmtNum(out.plasma)}` : noPower);
        break;
      }
      case 'shield': {
        const live = v('plasma') > 0;
        out = Object.fromEntries(t.outputs.map((o) => [o, live ? p[o] : 0]));
        say(live ? `radius ${fmtNum(v('radius'))} m` : 'no plasma');
        break;
      }
      case 'wireless': {
        const c = this.channels.get(p.channel);
        const sending = !!this.incoming.get(inst.id).tx;
        if (c && c.senders.length > 1) { say(`CONFLICT ch ${p.channel}`); out = { rx: 0 }; break; }
        const sender = c && c.senders[0];
        out = { rx: sender && sender !== inst ? this._readPort(sender.id, 'tx') : 0 };
        say(sending ? `tx ch ${p.channel}` : `rx ch ${p.channel}`);
        break;
      }
      default: throw new Error('no handler for behaviour ' + t.behavior);
    }
    if (t.demand === 'change') s.prevDemandIn = t.inputs.length ? v(t.inputs[0]) : 0;
    return out;
  }

  step(n = 1) { for (let i = 0; i < n; i++) this._step(); }

  snapshot() {
    const out = {};
    for (const [id, inst] of this.instances) out[id] = { ...inst.outputs };
    return out;
  }
}

if (typeof module !== 'undefined') module.exports = { CircuitEngine, TYPES, STATEFUL, portKind, isPowerPort, DIFF_INTERVALS };
