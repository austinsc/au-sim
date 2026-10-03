'use strict';
// Generates circuits/planet_hop_flip.json.  Run: node tools/build_planet_hop_flip.js
// Fly it against the flip model:              node tools/flip_harness.js
//
// Flip-and-burn autopilot: burn toward the target nose first, then at the last safe moment turn the ship 180°
// with the RCS and burn the same engines to stop. The turn takes time, and the ship coasts through it at full
// speed, so the turn is planned in: the flip starts when the distance left, less the coast during the turn,
// is what the engines need to stop. After the stop it holds the ship against gravity (tail down) until the
// Autopilot switch goes off.
//
//   vf        = Z SPEED: a Velocity Meter in Directional mode facing forward, signed (+ nose first)
//   distance  = committed ? (REAR DIST, or 0 while the tail meter sees nothing) : FWD DIST
//               (ch 30 Space Scanner on the nose; ch 38 Long Range Distance Meter on the tail. The meter is a single
//               ray, so it reads only once the tail points into the target's disk. Reading 0 until then means
//               "brake now": the flip was timed for full braking, and if the tail never finds the target the ship
//               stops short and holds instead of coasting in blind.)
//   d_plan    = distance − (standoff + max(vf, 0) · lead)   lead = flip time + signal delay; 0 once flying tail first
//   a_held    = accelerometer − g, held from the burn before the flip: the engines' own acceleration (the
//               Accelerometer reads |dv/dt|, gravity included, and the burn runs with gravity toward the target)
//   v_prof    = max(√(1.9 · max(a_held − g, 1) · max(d_plan, 0)) − fade_w, 0)     a_held − g: braking against gravity
//               the closing speed to fly: the fastest that can still stop in time on 95% of the measured
//               acceleration, less the fade band, so riding inside the band never eats the margin
//   committed = latched once vf > v_prof has held for commit_ticks, until the Autopilot switch goes off
//               (Accumulator latch; the wait lets the accelerometer settle when Autopilot starts mid-flight. The
//               target lock does not reset it: when the tail meter loses the target, REAR DIST x valid passes one
//               tick of 1e20 (the validity remapper is a block behind), and that must not cancel a flip)
//   yaw       = sat((min(√(2 · α_plan · (180 − |θ|)), k · (180 − |θ|)) − p) ÷ rate_band)
//               θ = ∫ yaw rate since the commit, p = d|θ|/dt: turn at the rate it can still stop from, decelerating
//               at α_plan (below the thrusters' real α); the linear term (k = tail_gain per s) takes over in the last
//               degrees and turns negative past 180°, so an overshoot is pulled back and the tail meter stays on target
//   holds     the engines push slightly off the centre of mass, and any offset turns the ship over a long burn,
//               so from Autopilot on the circuit holds pitch, and yaw until the flip, where they were:
//               cmd = sat(−(hold_kp · angle + rate) ÷ hold_band), angle = ∫ rate since Autopilot went on
//               (Accumulators, reset while it is off, so the holds send nothing then and the joystick has the ship)
//               -> PIT+ 14 / PIT− 15, and YAW± before the flip. Unlike the turn these need the sign: each Axis
//               Rotometer must read positive for nose right (yaw) and nose up (pitch), the game's rule (+ω about the
//               part's +y, torque = position × force) for an upright one and one lying along -x... see the ship notes.
//   thrust    = !committed ? (Autopilot AND FWD DIST sees a target)
//                          : aligned · (fade + g ÷ a_held)
//               fade = sat(−(vf + v_prof) ÷ fade_w): +1 closing fade_w faster than v_prof, −1 fade_w slower (or
//               receding); g ÷ a_held: the throttle that holds the ship against gravity, so once v_prof reaches 0
//               it hovers tail down instead of falling or backing away; aligned: 0 below 170° turned, 1 from 178°
//
//   joystick  the pilot's Joystick 3D adds into the yaw and pitch commands and drives roll, so this circuit is the one
//             sender on all six attitude channels (the game allows one per channel): with Autopilot off the holds send
//             nothing and the stick flies the ship on the maneuvering thrusters; with it on, the holds pull back
//
// The turn needs no sign: the yaw command starts positive, |θ| grows whichever way that turns the ship, and the
// controller only ever reasons about |θ| and its rate, so the RCS mode and rotometer signs cannot make it run
// away. Radio follows the ship's channel standard (SHIP RADIOS, second tab): in 30 FWD DIST, 38 REAR DIST,
// 23 Z SPEED; out 1 THRUST CTL, 10 ROLL+ CTL, 11 ROLL− CTL, 12 YAW+ CTL, 13 YAW− CTL, 14 PIT+ CTL, 15 PIT− CTL,
// 31 SCAN ANGLE (the cone knob). Joystick: yaw +1 = nose right (YAW+), pitch +1 = nose up (PIT+), roll +1 = roll right.
const fs = require('fs');
const path = require('path');

// tuning (see flip_harness.js): the flip time comes from the ship's yaw inertia and RCS torque
const TUNE = {
  lead_s: Number(process.env.LEAD_S || 16),    // seconds of travel planned for the turn plus signal delay
  standoff_m: Number(process.env.STANDOFF || 150), // plan to stop this far short of the surface (tail meter)
  alpha_plan: Number(process.env.ALPHA_PLAN || 3), // deg/s² the turn plans to brake at (the RCS's real α is higher)
  rate_band: 4,                                // full yaw command at this turning-rate error (deg/s)
  tail_gain: 2,                                // deg/s of turn rate per degree left, near 180° and past it
  hold_kp: 2,                                  // attitude holds: deg/s of rate wanted per degree off
  hold_band: 10,                               // ... full thrust at this much (kp · angle + rate), deg/s
  aligned_from: 170, aligned_to: 178,          // braking thrust ramps in over this part of the turn (deg)
  fade_w: Number(process.env.FADE_W || 120),   // speed error for full thrust (m/s): loop gain a ÷ fade_w per s
  commit_ticks: Number(process.env.COMMIT_TICKS || 20),                            // ticks of `want` before the flip (the accelerometer settles in ~30)
  scan: 0.8,                                   // knob start: Space Scanner cone 50 − 49 × 0.8 = 10.8°
};
const A = 60;                                  // the Accumulator adds deg/s every tick: 60 per degree
const BLIND = [1e18, 1e19];                    // sensors read 1e20 when they see nothing

// [id, type_id, params, col, row]
const N = [
  // ---- radio in (receivers: no wire on tx) and local sensors ----
  ['rx_fwd',      'wireless_transmitter', { channel: 30 }, 0, 0],   // FWD DIST: Space Scanner, nose
  ['rx_rear',     'wireless_transmitter', { channel: 38 }, 0, 1],   // REAR DIST: Long Range Distance Meter, tail
  ['rx_vz',       'wireless_transmitter', { channel: 23 }, 0, 3],   // Z SPEED: Velocity Meter, directional, forward
  ['accel',       'accelerometer', { acceleration: 0 }, 0, 5],
  ['grav',        'gravitymeter', { gravity: 0 }, 0, 6],
  ['yaw_rate',    'axis_rotometer', { angular_velocity: 0 }, 0, 8],    // upright: + for nose right
  ['pitch_rate',  'axis_rotometer', { angular_velocity: 0 }, 0, 15],   // on its side: + for nose up
  ['joystick',    'joystick_3d', { yaw: 0, pitch: 0, roll: 0 }, 0, 18],
  ['sw_auto',     'switch', { out: 0 }, 0, 10],
  ['knob_scan',   'small_knob', { out: TUNE.scan }, 0, 12],
  ['tx_scan',     'wireless_transmitter', { channel: 31 }, 1, 12],  // SCAN ANGLE

  // ---- enable, target lock and the flip latch ----
  ['auto_r',      'data_router_2', {}, 1, 10],
  ['lock',        'min', {}, 2, 10],                                // Autopilot AND a target ahead
  ['off',         'condition', { op: 4 }, 3, 11],                  // Autopilot ≤ 0 ? 1 : 0
  ['off_r',       'data_router_4', {}, 3, 12],
  ['committed',   'accumulator', { mode: 0 }, 4, 11],              // counts ticks of `want`; reset while off
  ['notc',        'remapper', { in_min: TUNE.commit_ticks, in_max: TUNE.commit_ticks + 1, out_min: 1, out_max: 0 }, 5, 12],
  ['notc_r',      'data_router_4', {}, 5, 11],                     // 1 before the flip, 0 from it on

  // ---- distance ----
  ['rear_r',      'data_router_2', {}, 1, 1],
  ['rear_ok',     'remapper', { in_min: BLIND[0], in_max: BLIND[1], out_min: 1, out_max: 0 }, 2, 2],
  ['rear_eff',    'multiplier', {}, 3, 1],                         // REAR DIST, or 0 when it sees nothing
  ['rear_sel',    'condition', { op: 4 }, 4, 0],                   // flipped ? rear : FWD DIST
  ['d_plan',      'subtractor', {}, 5, 0],
  ['d_plan_r',    'data_router_2', {}, 6, 0],
  ['valid',       'remapper', { in_min: BLIND[0], in_max: BLIND[1], out_min: 1, out_max: 0 }, 7, 1],

  // ---- speed ----
  ['vz_r',        'data_router_4', {}, 1, 3],
  ['lead',        'remapper', { in_min: 0, in_max: 1e5, out_min: TUNE.standoff_m, out_max: TUNE.standoff_m + 1e5 * TUNE.lead_s }, 2, 3],

  // ---- braking acceleration and the stopping profile ----
  ['acc_net',     'subtractor', {}, 1, 4],                         // accelerometer − g: the engines' acceleration
  ['a_held',      'memory', { mode: 0 }, 1, 5],                     // tracks it until the flip
  ['a_held_r',    'data_router_2', {}, 2, 5],
  ['grav_r',      'data_router_4', {}, 1, 6],
  ['a_net',       'subtractor', {}, 3, 5],                         // a_held − gravity
  ['two_a',       'remapper', { in_min: 1, in_max: 1000, out_min: 1.9, out_max: 1900 }, 4, 5],   // 1.9 · max(a, 1)
  ['d_pos',       'remapper', { in_min: 0, in_max: 1e15, out_min: 0, out_max: 1e15 }, 7, 2],    // max(d_plan, 0)
  ['prof2',       'multiplier', {}, 8, 3],
  ['v_root',      'sqrt', {}, 9, 3],
  ['v_prof',      'remapper', { in_min: TUNE.fade_w, in_max: 1e9, out_min: 0, out_max: 1e9 - TUNE.fade_w }, 10, 2],
  ['v_prof_r',    'data_router_2', {}, 10, 3],
  ['want',        'condition', { op: 3 }, 11, 2],                  // vf > v_prof ? 1 : 0
  ['err',         'adder', {}, 11, 4],                             // vf + v_prof: < 0 when closing too fast

  // ---- the turn ----
  ['theta',       'accumulator', { mode: 0 }, 1, 8],               // ∫ yaw rate (deg/s per tick) since Autopilot on
  ['theta_r0',    'data_router_4', {}, 2, 9],
  ['abs_theta',   'abs', {}, 2, 8],
  ['yh_p',        'remapper', { in_min: -1e7, in_max: 1e7, out_min: -1e7 * TUNE.hold_kp / A, out_max: 1e7 * TUNE.hold_kp / A }, 3, 10],
  ['yh_d',        'differentiator', { interval: 1 }, 3, 11],         // yaw rate, 0 while off
  ['yh',          'adder', {}, 4, 10],
  ['u_hold',      'remapper', { in_min: -TUNE.hold_band, in_max: TUNE.hold_band, out_min: 1, out_max: -1 }, 5, 10],
  ['theta_r',     'data_router_4', {}, 3, 8],
  ['progress',    'differentiator', { interval: 1 }, 4, 9],         // d|θ| per tick, in deg/s: + while turning on
  ['two_a_rem',   'remapper', { in_min: 0, in_max: 180 * A, out_min: 2 * TUNE.alpha_plan * 180, out_max: 0 }, 4, 8],
  ['rate_root',   'sqrt', {}, 5, 8],                               // √(2 α_plan · degrees left)
  ['rate_lin',    'remapper', { in_min: 0, in_max: 360 * A, out_min: 180 * TUNE.tail_gain, out_max: -180 * TUNE.tail_gain }, 4, 10],
  ['rate_cmd',    'min', {}, 5, 9],
  ['rate_err',    'subtractor', {}, 6, 9],
  ['u',           'remapper', { in_min: -TUNE.rate_band, in_max: TUNE.rate_band, out_min: -1, out_max: 1 }, 6, 8],
  ['u_gated',     'condition', { op: 4 }, 7, 8],                   // flipped ? turn : hold
  ['yaw_sum',     'adder', {}, 8, 7],                               // turn or hold, plus the stick
  ['yaw_split',   'sign_splitter', {}, 8, 8],
  ['tx_yaw_pos',  'wireless_transmitter', { channel: 12 }, 9, 8],  // YAW+ CTL
  ['tx_yaw_neg',  'wireless_transmitter', { channel: 13 }, 9, 9],  // YAW− CTL

  // ---- pitch hold ----
  ['phi',         'accumulator', { mode: 0 }, 1, 15],              // ∫ pitch rate since Autopilot on
  ['phi_r',       'data_router_2', {}, 2, 15],
  ['ph_p',        'remapper', { in_min: -1e7, in_max: 1e7, out_min: -1e7 * TUNE.hold_kp / A, out_max: 1e7 * TUNE.hold_kp / A }, 3, 15],
  ['ph_d',        'differentiator', { interval: 1 }, 3, 16],
  ['ph',          'adder', {}, 4, 15],
  ['u_pitch',     'remapper', { in_min: -TUNE.hold_band, in_max: TUNE.hold_band, out_min: 1, out_max: -1 }, 5, 15],
  ['pitch_sum',   'adder', {}, 6, 14],                              // hold, plus the stick
  ['pitch_split', 'sign_splitter', {}, 6, 15],
  ['tx_pit_pos',  'wireless_transmitter', { channel: 14 }, 7, 15], // PIT+ CTL
  ['tx_pit_neg',  'wireless_transmitter', { channel: 15 }, 7, 16], // PIT− CTL
  ['roll_split',  'sign_splitter', {}, 6, 18],
  ['tx_roll_pos', 'wireless_transmitter', { channel: 10 }, 7, 18], // ROLL+ CTL
  ['tx_roll_neg', 'wireless_transmitter', { channel: 11 }, 7, 19], // ROLL− CTL

  // ---- thrust ----
  ['aligned',     'remapper', { in_min: TUNE.aligned_from * A, in_max: TUNE.aligned_to * A, out_min: 0, out_max: 1 }, 4, 7],
  ['fade',        'remapper', { in_min: -TUNE.fade_w, in_max: TUNE.fade_w, out_min: 1, out_max: -1 }, 12, 4],
  ['g_a',         'divider', {}, 3, 6],                            // g ÷ a_held: the hover throttle
  ['hold_sum',    'adder', {}, 12, 5],
  ['brake_out',   'multiplier', {}, 12, 6],
  ['thrust',      'condition', { op: 3 }, 13, 6],                  // before the flip ? lock : braking
  ['tx_thrust',   'wireless_transmitter', { channel: 1 }, 14, 6],  // THRUST CTL
];

const E = `
sw_auto.out auto_r.in
auto_r.a off.a
auto_r.b lock.a
valid.out lock.b
lock.out thrust.true
off.out off_r.in
off_r.a committed.reset
off_r.b theta.reset
off_r.c phi.reset
want.out committed.in
committed.out notc.in
notc.out notc_r.in
notc_r.a rear_sel.a
notc_r.b u_gated.a
notc_r.c thrust.a
notc_r.d a_held.set

rx_rear.rx rear_r.in
rear_r.a rear_ok.in
rear_r.b rear_eff.a
rear_ok.out rear_eff.b
rear_eff.out rear_sel.true
rx_fwd.rx rear_sel.false
rear_sel.out d_plan.a
lead.out d_plan.b
d_plan.out d_plan_r.in
d_plan_r.a d_pos.in
d_plan_r.b valid.in

rx_vz.rx vz_r.in
vz_r.a want.a
vz_r.b err.a
vz_r.c lead.in

accel.acceleration acc_net.a
grav_r.c acc_net.b
acc_net.out a_held.value
a_held.out a_held_r.in
a_held_r.a a_net.a
a_held_r.b g_a.b
grav.gravity grav_r.in
grav_r.a a_net.b
grav_r.b g_a.a
a_net.out two_a.in
two_a.out prof2.a
d_pos.out prof2.b
prof2.out v_root.in
v_root.out v_prof.in
v_prof.out v_prof_r.in
v_prof_r.a want.b
v_prof_r.b err.b

yaw_rate.angular_velocity theta.in
theta.out theta_r0.in
theta_r0.a abs_theta.in
theta_r0.b yh_p.in
theta_r0.c yh_d.in
yh_p.out yh.a
yh_d.out yh.b
yh.out u_hold.in
u_hold.out u_gated.false
abs_theta.out theta_r.in
theta_r.a progress.in
theta_r.b two_a_rem.in
theta_r.c aligned.in
two_a_rem.out rate_root.in
theta_r.d rate_lin.in
rate_root.out rate_cmd.a
rate_lin.out rate_cmd.b
rate_cmd.out rate_err.a
progress.out rate_err.b
rate_err.out u.in
u.out u_gated.true
u_gated.out yaw_sum.a
joystick.yaw yaw_sum.b
yaw_sum.out yaw_split.in
yaw_split.pos tx_yaw_pos.tx
yaw_split.neg tx_yaw_neg.tx

err.out fade.in
fade.out hold_sum.a
g_a.out hold_sum.b
hold_sum.out brake_out.a
aligned.out brake_out.b
brake_out.out thrust.false
thrust.out tx_thrust.tx

pitch_rate.angular_velocity phi.in
phi.out phi_r.in
phi_r.a ph_p.in
phi_r.b ph_d.in
ph_p.out ph.a
ph_d.out ph.b
ph.out u_pitch.in
u_pitch.out pitch_sum.a
joystick.pitch pitch_sum.b
pitch_sum.out pitch_split.in
pitch_split.pos tx_pit_pos.tx
pitch_split.neg tx_pit_neg.tx
joystick.roll roll_split.in
roll_split.pos tx_roll_pos.tx
roll_split.neg tx_roll_neg.tx

knob_scan.out tx_scan.tx
`.trim().split('\n').filter((l) => l.trim()).map((l) => {
  const [f, t] = l.trim().split(/\s+/);
  const [from_instance, from_port] = f.split('.');
  const [to_instance, to_port] = t.split('.');
  return { from_instance, from_port, to_instance, to_port, color: '#e9c46a' };
});

// Sanity: every wire names real blocks, no output drives two inputs, no input has two drivers.
const ids = new Set(N.map((n) => n[0]));
const usedOut = new Set(), usedIn = new Set();
for (const e of E) {
  for (const id of [e.from_instance, e.to_instance]) if (!ids.has(id)) throw new Error('unknown block ' + id);
  const k = e.from_instance + '.' + e.from_port, j = e.to_instance + '.' + e.to_port;
  if (usedOut.has(k)) throw new Error('output drives two inputs: ' + k);
  if (usedIn.has(j)) throw new Error('input has two drivers: ' + j);
  usedOut.add(k); usedIn.add(j);
}

const diagram = {
  instances: N.map(([id, type_id, parameters, c, r]) => ({
    id, type_id, parameters, position: { x: 40 + c * 240, y: 40 + r * 165 }, color: '#e9c46a', mirrored: false,
  })),
  edges: E, groups: [], max_per_column: 4, max_rows: 4, max_columns: 8,
  tune: TUNE,
};
const out = path.join(__dirname, '..', 'circuits', 'planet_hop_flip.json');
fs.writeFileSync(out, JSON.stringify(diagram, null, 2) + '\n');
const count = (ns, es, file) => {
  const radio = ns.filter((n) => n.type_id === 'wireless_transmitter').length;
  const routers = ns.filter((n) => n.type_id.startsWith('data_router')).length;
  console.log(`${file}: ${ns.length} blocks (${radio} radio, ${routers} Data Routers, 0 constants), ${es.length} wires; lead ${TUNE.lead_s} s, standoff ${TUNE.standoff_m} m, fade ${TUNE.fade_w} m/s`);
};
count(diagram.instances, E, 'planet_hop_flip.json');

// A cockpit version (circuits/flight_computer.json) for a ship whose dash carries the controls:
//   - the Autopilot switch sits on the dash, so here it is an outside input (a toggle: bpgen leaves a cable stub),
//     and so do the two Axis Rotometers (sliders), where they can be turned over if one reads the wrong sign, and the
//     Joystick 3D (three sliders, one cable each);
//   - the scan knob and its SCAN ANGLE transmitter sit on the dash too;
//   - landing gear: GEAR (ch 69) = 1 below 100 m of GROUND DIST (ch 9, a downward Long Range Distance Meter), 0 above
//     105 m or when the meter sees nothing; each Extendable Damper has its own receiver on 69.
const FC_DROP = new Set(['knob_scan', 'tx_scan']);
const fc = JSON.parse(JSON.stringify(diagram));
fc.instances = fc.instances.filter((i) => !FC_DROP.has(i.id));
fc.instances.find((i) => i.id === 'sw_auto').type_id = 'toggle';
for (const id of ['yaw_rate', 'pitch_rate']) fc.instances.find((i) => i.id === id).type_id = 'slider';
// the joystick: one outside input per axis, so each gets its own cable stub
const joy = fc.instances.find((i) => i.id === 'joystick');
fc.instances = fc.instances.filter((i) => i !== joy);
for (const [k, ax] of ['yaw', 'pitch', 'roll'].entries()) {
  fc.instances.push({ ...joy, id: `joy_${ax}`, type_id: 'slider', parameters: { value: 0 }, position: { x: joy.position.x, y: joy.position.y + 120 * k } });
}
for (const e of fc.edges) if (e.from_instance === 'joystick') { e.from_instance = `joy_${e.from_port}`; e.from_port = 'out'; }
fc.edges = fc.edges.filter((e) => !FC_DROP.has(e.from_instance) && !FC_DROP.has(e.to_instance));
const gear = [
  ['rx_ground', 'wireless_transmitter', { channel: 9 }, 0, 14],     // GROUND DIST
  ['gear_rem',  'remapper', { in_min: 100, in_max: 105, out_min: 1, out_max: 0 }, 1, 14],
  ['tx_gear',   'wireless_transmitter', { channel: 69 }, 2, 14],    // GEAR
];
for (const [id, type_id, parameters, c, r] of gear) {
  fc.instances.push({ id, type_id, parameters, position: { x: 40 + c * 240, y: 40 + r * 165 }, color: '#e9c46a', mirrored: false });
}
fc.edges.push({ from_instance: 'rx_ground', from_port: 'rx', to_instance: 'gear_rem', to_port: 'in', color: '#e9c46a' },
  { from_instance: 'gear_rem', from_port: 'out', to_instance: 'tx_gear', to_port: 'tx', color: '#e9c46a' });
fs.writeFileSync(path.join(__dirname, '..', 'circuits', 'flight_computer.json'), JSON.stringify(fc, null, 2) + '\n');
count(fc.instances.filter((i) => !['toggle', 'slider'].includes(i.type_id)), fc.edges, 'flight_computer.json (switch, rotometers and joystick on the dash)');
