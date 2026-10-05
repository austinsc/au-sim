'use strict';
// Generates circuits/wormhole_nav.json.  Run: node tools/build_wormhole_nav.js
// Fly it against the black hole model:   node tools/wormhole_harness.js
//
// Wormhole navigation: takes a ship with forward thrusters only down the black hole's tunnel axis, turn and burn,
// keeping its joints out of the game's strain rule. Line the ship up by eye on the tunnel's axis, nose at the black
// hole, and switch Autopilot on. It burns in, turns round, brakes, and holds where its thrust can still hover (gravity
// at 80% of it). Switch Descend on (before or after the hold) to go on in. It then falls with the net acceleration
// held at a_safe while its thrust can do that, and burns full tail-first once it cannot, the least strain the ship
// can have. Press R when the game offers the wormhole.
//
// Why (game code, see PROJECT_SUMMARY.md, "Joint strain" and "Black hole"):
//   - a part whose velocity changes by more than 0.173 m/s in a tick (a net 10.39 m/s², gravity in free fall included)
//     takes 0.22 · mass · Δv² of strain, and a joint breaks if one tick's strain exceeds its strength (Iron 1600);
//   - the black hole pulls 1000 · (600 km / r)² m/s² (all three worlds; no disk in this one), capped near 200 m/s²
//     inside the tunnel. Speed costs no strain, net acceleration does: so the circuit never holds the net acceleration
//     above a_safe where thrust can prevent it, and past that point burns full against gravity.
//
//   inputs   Z SPEED (ch 23): Velocity Meter, Directional, facing forward (+ nose first). Accelerometer, Gravitymeter,
//            Axis Rotometers for yaw (+ nose right) and pitch (+ nose up), Joystick 3D, Autopilot and Descend switches
//   outputs  THRUST CTL (1); YAW+/YAW− (12/13), PIT+/PIT− (14/15), ROLL+/ROLL− (10/11): the SHIP RADIOS standard. The
//            stick adds into yaw and pitch and drives roll, so this is the one sender on all six attitude channels.
//
//   g         Gravitymeter: the black hole's pull, which gives the range too, r = √(GM / g), GM = 3.6e14 m³/s²
//   timer     ticks since Autopilot went on (an Accumulator of the switch, reset while it is off)
//   measure   for measure_ticks after Autopilot on, full thrust nose first; then a = accelerometer − g is held (the
//             Accelerometer reads |dv/dt|, gravity included, and the burn runs with gravity toward the hole)
//   a_p       min(c_brake · a, a_safe): the braking the plan counts on
//   u_prof    m_prof · √(2 √GM · (a_p / √g + √g − k_h · √a_p)) − v_shift, at least 0: the closing speed it can still
//             stop from at the hold, braking at a_p against the inverse-square pull. The work braking does from r down
//             to the hold is a_p · (r − r_h) + GM · (1/r − 1/r_h), and with r = √(GM / g) that is √GM times
//             (a_p / √g + √g) less its value at the hold; the hold is where g = c_hold · a_p, so that value is
//             k_h · √a_p, k_h = (1 + c_hold) / √c_hold. Holding short of where braking runs out (c_hold < 1) leaves it
//             braking power to the end, so the approach ends in finite time (at c_hold 1 it crept in exponentially).
//   flipped   latched once vf > c_flip · u_prof has held for commit_ticks (measured first), until Autopilot goes off
//   σ         +1 before the flip (nose first), −1 after; u = σ · vf, the closing speed
//   a_des     net closing acceleration wanted: sat(k_speed · (u_prof − u)) within ±a_safe, or +a_safe with Descend on
//   thrust    measuring ? 1 : sat(σ · (a_des − g) ÷ a, 0..1) · max(σ, aligned)
//             the thrust that makes the net closing acceleration a_des: so it never goes past ±a_safe while the
//             engines can stop it; aligned (0 below 170° turned, 1 from 178°) keeps it off through the turn
//   turn      quick turn v2's: its first half second at full yaw measures the ship's yaw authority, which sets the
//             braking plan and the loop gain (measured: coasting, it reads ~0.27 · α)
//   holds     pitch, and yaw until the flip, held where they were at Autopilot on (PD on the integrated rotometer
//             rates, planet_hop_flip's): the engines push slightly off the centre of mass
const fs = require('fs');
const path = require('path');

const num = (k, d) => (process.env[k] === undefined ? d : Number(process.env[k]));
const TUNE = {
  gm: 3.6e14,                          // m³/s²: 1000 m/s² at 600 km, the game's black hole (CRPBlackHoleFeature)
  a_safe: num('A_SAFE', 9),            // m/s²: net acceleration it keeps to (strain starts at 10.39)
  c_brake: num('C_BRAKE', 0.8),        // plan braking on this share of the measured thrust
  c_hold: num('C_HOLD', 0.6),          // hold where gravity is this share of that (the rest brakes the last metres)
  m_prof: num('M_PROF', 0.9),          // speed margin on the profile
  v_shift: num('V_SHIFT', 20),         // m/s: the profile, shifted down, reaches 0 (the hold) in finite time
  c_flip: num('C_FLIP', 0.7),          // turn round once closing at this share of the profile speed
  k_speed: num('K_SPEED', 0.3),        // 1/s: net acceleration per m/s of speed error
  measure_ticks: 180,                  // full thrust this long after Autopilot on, then a is held
  commit_ticks: 20,                    // ticks of `want` before the flip
  turn_measure: 30, c_plan: 1.0, c_band: 1.6, a_min: 0.5, tail_gain: 2,   // the turn (quick turn v2)
  hold_kp: 2, hold_band: 10,           // attitude holds: deg/s wanted per degree off; full output at this (deg/s)
  aligned_from: 170, aligned_to: 178,  // braking thrust ramps in over this part of the turn (deg)
};
const A = 60;                                        // the Accumulator adds deg/s every tick: 60 per degree
const KH = (1 + TUNE.c_hold) / Math.sqrt(TUNE.c_hold);
const S2 = 2 * Math.sqrt(TUNE.gm);                   // 2 √GM
const BIG = 1e4;

// [id, type_id, params, col, row]
const N = [
  // ---- inputs ----
  ['rx_vz',          'wireless_transmitter', { channel: 23 }, 0, 4],   // Z SPEED: Velocity Meter, directional, forward
  ['accelerometer',  'accelerometer', { acceleration: 0 }, 0, 2],
  ['gravitymeter',   'gravitymeter', { gravity: 0 }, 0, 3],
  ['yaw_rate',       'axis_rotometer', { angular_velocity: 0 }, 0, 9],   // upright: + for nose right
  ['pitch_rate',     'axis_rotometer', { angular_velocity: 0 }, 0, 15],  // on its side: + for nose up
  ['joystick',       'joystick_3d', { yaw: 0, pitch: 0, roll: 0 }, 0, 17],
  ['autopilot',        'switch', { out: 0 }, 0, 0],
  ['descend',        'switch', { out: 0 }, 0, 6],                        // Descend

  // ---- Autopilot, the timer and the thrust measurement ----
  ['auto_r',         'data_router_4', {}, 1, 0],
  ['off',            'condition', { op: 4 }, 2, 0],                     // Autopilot ≤ 0 ? 1 : 0
  ['off_r',          'data_router_4', {}, 3, 0],
  ['timer',          'accumulator', { mode: 0 }, 2, 1],                 // ticks since Autopilot on
  ['meas_done',      'remapper', { in_min: TUNE.measure_ticks - 1, in_max: TUNE.measure_ticks, out_min: 0, out_max: 1 }, 3, 1],
  ['meas_r',         'data_router_4', {}, 4, 1],
  ['grav_r',         'data_router_4', {}, 1, 3],
  ['acc_net',        'subtractor', {}, 2, 2],                           // accelerometer − g
  ['a_held',         'memory', { mode: 1 }, 3, 2],                       // a, as the measurement ends
  ['a_r',            'data_router_2', {}, 4, 2],
  ['a_plan',         'remapper', { in_min: 0, in_max: TUNE.a_safe / TUNE.c_brake, out_min: 0, out_max: TUNE.a_safe }, 5, 2],
  ['ap_r',           'data_router_2', {}, 6, 2],
  ['sap',            'sqrt', {}, 7, 2],                                 // √a_p
  ['khs',            'remapper', { in_min: 0, in_max: 100, out_min: 0, out_max: 100 * KH }, 8, 2],   // k_h · √a_p

  // ---- the stopping profile ----
  ['sg',             'sqrt', {}, 2, 3],                                 // √g
  ['sg_r',           'data_router_2', {}, 3, 3],
  ['apg',            'divider', {}, 7, 3],                              // a_p ÷ √g
  ['sum1',           'adder', {}, 8, 3],                                // a_p / √g + √g
  ['e1',             'subtractor', {}, 9, 3],                           // ... − k_h √a_p
  ['e2',             'remapper', { in_min: 0, in_max: BIG, out_min: 0, out_max: S2 * BIG }, 10, 3],   // × 2 √GM, at least 0
  ['uraw',           'sqrt', {}, 11, 3],
  ['u_prof',         'remapper', { in_min: TUNE.v_shift / TUNE.m_prof, in_max: 1e6, out_min: 0, out_max: TUNE.m_prof * 1e6 - TUNE.v_shift }, 12, 3],
  ['up_r',           'data_router_2', {}, 10, 3],
  ['flip_at',        'remapper', { in_min: 0, in_max: 1e7, out_min: 0, out_max: TUNE.c_flip * 1e7 }, 11, 4],

  // ---- the flip latch ----
  ['vz_r',           'data_router_2', {}, 1, 4],
  ['want',           'condition', { op: 3 }, 12, 4],                    // vf > c_flip · u_prof ? measured : 0
  ['committed',      'accumulator', { mode: 0 }, 13, 4],                // ticks of `want`; reset while off
  ['flipped',        'remapper', { in_min: TUNE.commit_ticks, in_max: TUNE.commit_ticks + 1, out_min: 0, out_max: 1 }, 14, 4],
  ['fl_r',           'data_router_4', {}, 15, 4],
  ['sigma',          'remapper', { in_min: 0, in_max: 1, out_min: 1, out_max: -1 }, 16, 5],   // +1 nose first, −1 tail first
  ['sigma_r',        'data_router_4', {}, 17, 5],

  // ---- speed loop and thrust ----
  ['u',              'multiplier', {}, 2, 5],                            // σ · vf: closing speed
  ['err',            'subtractor', {}, 11, 5],                           // u_prof − u
  ['a_norm',         'remapper', { in_min: -TUNE.a_safe / TUNE.k_speed, in_max: TUNE.a_safe / TUNE.k_speed, out_min: -1, out_max: 1 }, 12, 5],
  ['a_sel',          'condition', { op: 1 }, 13, 6],                     // Descend ≠ 0 ? 1 : a_norm
  ['a_des',          'remapper', { in_min: -1, in_max: 1, out_min: -TUNE.a_safe, out_max: TUNE.a_safe }, 14, 6],
  ['t_in',           'subtractor', {}, 15, 6],                           // a_des − g: the engines' closing share
  ['t_sig',          'multiplier', {}, 16, 6],                           // along the nose
  ['thr',            'divider', {}, 17, 6],                              // ÷ a
  ['thr_c',          'remapper', { in_min: 0, in_max: 1, out_min: 0, out_max: 1 }, 18, 6],
  ['gate',           'max', {}, 18, 5],                                  // max(σ, aligned): 1 before the flip
  ['thr_g',          'multiplier', {}, 19, 6],
  ['thrust_out',     'condition', { op: 1 }, 20, 6],                     // measured ≠ 0 ? thr_g : Autopilot
  ['tx_thrust',      'wireless_transmitter', { channel: 1 }, 21, 6],     // THRUST CTL

  // ---- the turn (quick turn v2) ----
  ['theta',          'accumulator', { mode: 0 }, 1, 9],                  // ∫ yaw rate since Autopilot on: 60 × degrees
  ['theta_r0',       'data_router_4', {}, 2, 9],
  ['abs_theta',      'abs', {}, 3, 9],
  ['theta_r',        'data_router_4', {}, 4, 9],
  ['progress',       'differentiator', { interval: 1, simulate: 0 }, 5, 10],   // p = d|θ| per tick, deg/s
  ['prog_r',         'data_router_2', {}, 6, 10],
  ['turn_meas',      'delay', { ticks: TUNE.turn_measure }, 5, 12],      // flipped, half a second late
  ['tm_r',           'data_router_2', {}, 6, 12],
  ['measured',       'memory', { mode: 1 }, 7, 12],                      // p half a second into the turn
  ['ship_alpha',     'remapper', { in_min: 0, in_max: 1000, out_min: TUNE.c_band * TUNE.a_min, out_max: TUNE.c_band * (1000 + TUNE.a_min) }, 8, 12],
  ['alpha_r',        'data_router_2', {}, 9, 12],
  ['braking_room',   'remapper', { in_min: 0, in_max: 180 * A, out_min: 360 * TUNE.c_plan / TUNE.c_band, out_max: 0 }, 5, 9],
  ['braking_scaled', 'multiplier', {}, 10, 9],
  ['rate_sqrt',      'sqrt', {}, 11, 9],
  ['rate_lin',       'remapper', { in_min: 0, in_max: 360 * A, out_min: TUNE.tail_gain * 180, out_max: -TUNE.tail_gain * 180 }, 5, 11],
  ['rate_cmd',       'min', {}, 12, 10],
  ['rate_err',       'subtractor', {}, 13, 10],
  ['rate_norm',      'divider', {}, 14, 10],
  ['steer',          'condition', { op: 1 }, 15, 10],                     // measuring ≠ 0 ? rate_norm : flipped
  ['u_turn',         'remapper', { in_min: -1, in_max: 1, out_min: -1, out_max: 1 }, 16, 10],
  ['aligned',        'remapper', { in_min: TUNE.aligned_from * A, in_max: TUNE.aligned_to * A, out_min: 0, out_max: 1 }, 17, 8],

  // ---- yaw: hold until the flip, then the turn; plus the stick ----
  ['yh_p',           'remapper', { in_min: -1e7, in_max: 1e7, out_min: -1e7 * TUNE.hold_kp / A, out_max: 1e7 * TUNE.hold_kp / A }, 3, 8],
  ['yh_d',           'differentiator', { interval: 1, simulate: 0 }, 3, 7],
  ['yh',             'adder', {}, 4, 7],
  ['u_hold',         'remapper', { in_min: -TUNE.hold_band, in_max: TUNE.hold_band, out_min: 1, out_max: -1 }, 5, 7],
  ['u_gated',        'condition', { op: 1 }, 17, 10],                     // flipped ≠ 0 ? turn : hold
  ['yaw_sum',        'adder', {}, 18, 10],
  ['yaw_split',      'sign_splitter', {}, 19, 10],
  ['tx_yaw_pos',     'wireless_transmitter', { channel: 12 }, 20, 10],    // YAW+ CTL
  ['tx_yaw_neg',     'wireless_transmitter', { channel: 13 }, 20, 11],    // YAW− CTL

  // ---- pitch hold, roll ----
  ['phi',            'accumulator', { mode: 0 }, 1, 15],                  // ∫ pitch rate since Autopilot on
  ['phi_r',          'data_router_2', {}, 2, 15],
  ['ph_p',           'remapper', { in_min: -1e7, in_max: 1e7, out_min: -1e7 * TUNE.hold_kp / A, out_max: 1e7 * TUNE.hold_kp / A }, 3, 15],
  ['ph_d',           'differentiator', { interval: 1, simulate: 0 }, 3, 16],
  ['ph',             'adder', {}, 4, 15],
  ['u_pitch',        'remapper', { in_min: -TUNE.hold_band, in_max: TUNE.hold_band, out_min: 1, out_max: -1 }, 5, 15],
  ['pitch_sum',      'adder', {}, 6, 15],
  ['pitch_split',    'sign_splitter', {}, 7, 15],
  ['tx_pit_pos',     'wireless_transmitter', { channel: 14 }, 8, 15],     // PIT+ CTL
  ['tx_pit_neg',     'wireless_transmitter', { channel: 15 }, 8, 16],     // PIT− CTL
  ['roll_split',     'sign_splitter', {}, 6, 17],
  ['tx_roll_pos',    'wireless_transmitter', { channel: 10 }, 7, 17],     // ROLL+ CTL
  ['tx_roll_neg',    'wireless_transmitter', { channel: 11 }, 7, 18],     // ROLL− CTL
];

const E = `
autopilot.out auto_r.in
auto_r.a off.a
auto_r.b timer.in
auto_r.c thrust_out.false
off.out off_r.in
off_r.a timer.reset
off_r.b committed.reset
off_r.c theta.reset
off_r.d phi.reset
timer.out meas_done.in
meas_done.out meas_r.in
meas_r.a a_held.set
meas_r.b want.true
meas_r.c thrust_out.a

gravitymeter.gravity grav_r.in
accelerometer.acceleration acc_net.a
grav_r.a acc_net.b
acc_net.out a_held.value
a_held.out a_r.in
a_r.a a_plan.in
a_r.b thr.b
a_plan.out ap_r.in
ap_r.a sap.in
ap_r.b apg.a
sap.out khs.in
grav_r.b sg.in
sg.out sg_r.in
sg_r.a apg.b
sg_r.b sum1.b
apg.out sum1.a
sum1.out e1.a
khs.out e1.b
e1.out e2.in
e2.out uraw.in
uraw.out u_prof.in
u_prof.out up_r.in
up_r.a flip_at.in
up_r.b err.a

rx_vz.rx vz_r.in
vz_r.a want.a
flip_at.out want.b
want.out committed.in
committed.out flipped.in
flipped.out fl_r.in
fl_r.a sigma.in
sigma.out sigma_r.in
vz_r.b u.a
sigma_r.a u.b
u.out err.b
err.out a_norm.in
descend.out a_sel.a
a_norm.out a_sel.false
a_sel.out a_des.in
a_des.out t_in.a
grav_r.c t_in.b
t_in.out t_sig.a
sigma_r.b t_sig.b
t_sig.out thr.a
thr.out thr_c.in
sigma_r.c gate.a
aligned.out gate.b
thr_c.out thr_g.a
gate.out thr_g.b
thr_g.out thrust_out.true
thrust_out.out tx_thrust.tx

yaw_rate.angular_velocity theta.in
theta.out theta_r0.in
theta_r0.a abs_theta.in
theta_r0.b yh_p.in
theta_r0.c yh_d.in
abs_theta.out theta_r.in
theta_r.a progress.in
theta_r.b braking_room.in
theta_r.c rate_lin.in
theta_r.d aligned.in
progress.out prog_r.in
prog_r.a rate_err.b
prog_r.b measured.value
fl_r.b turn_meas.in
turn_meas.out tm_r.in
tm_r.a measured.set
tm_r.b steer.a
measured.out ship_alpha.in
ship_alpha.out alpha_r.in
alpha_r.a braking_scaled.b
alpha_r.b rate_norm.b
braking_room.out braking_scaled.a
braking_scaled.out rate_sqrt.in
rate_sqrt.out rate_cmd.a
rate_lin.out rate_cmd.b
rate_cmd.out rate_err.a
rate_err.out rate_norm.a
rate_norm.out steer.true
fl_r.d steer.false
steer.out u_turn.in
u_turn.out u_gated.true
yh_p.out yh.a
yh_d.out yh.b
yh.out u_hold.in
u_hold.out u_gated.false
fl_r.c u_gated.a
u_gated.out yaw_sum.a
joystick.yaw yaw_sum.b
yaw_sum.out yaw_split.in
yaw_split.pos tx_yaw_pos.tx
yaw_split.neg tx_yaw_neg.tx

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
`.trim().split('\n').filter((l) => l.trim()).map((l) => {
  const [f, t] = l.trim().split(/\s+/);
  const [from_instance, from_port] = f.split('.');
  const [to_instance, to_port] = t.split('.');
  return { from_instance, from_port, to_instance, to_port };
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

const notes = [
  'Wormhole navigation: takes a ship with forward thrusters only down the black hole\'s tunnel, turn and burn, keeping its joints out of the game\'s strain rule as long as its thrust can.',
  '',
  'Use',
  '- Line the ship up by eye on the tunnel\'s axis, nose at the black hole, nearly still, then switch Autopilot on. Start well away from any planet: the Gravitymeter is its range finder.',
  '- It burns in, turns round, brakes and holds where gravity is about half its thrust (at most 5.4 m/s²), with braking to spare.',
  '- Switch Descend on to go on in (before the hold too: it then goes straight in). Off again, it brakes and holds wherever it still can.',
  '- Press R when the game offers to travel through the black hole. Autopilot off cuts thrust: never do that deep in.',
  '',
  'Strain (game code)',
  '- A part whose velocity changes by more than 0.173 m/s in a tick (a net 10.4 m/s², gravity in free fall included) takes 0.22 x mass x dv² of strain; a joint breaks at Iron 1600, Nano 5000.',
  '- The circuit holds the net acceleration at 9 m/s² or under while its engines can. Deeper, gravity outgrows thrust and it burns full tail-first, the least strain there is: at the funnel mouth (2,400 km, 62 m/s²) Iron-jointed parts over about 8 t can break, at the tunnel\'s strongest pull (about 240 m/s², 900 km out) over about half a tonne. Speed itself costs nothing.',
  '',
  'Wiring (SHIP RADIOS)',
  '- In: Z SPEED (23) from a Velocity Meter, Directional, facing forward. Local: Accelerometer, Gravitymeter, yaw and pitch Axis Rotometers (+ for nose right, nose up), Joystick 3D, Autopilot and Descend switches.',
  '- Out: THRUST CTL (1), ROLL+/- (10/11), YAW+/- (12/13), PIT+/- (14/15). The stick adds into yaw and pitch and drives roll.',
  '- Electric main engines (fuel engines take 10-20 s to respond). The first 3 s after Autopilot on are a full-thrust measurement.',
  '',
  'Built and checked against a black hole model by tools/build_wormhole_nav.js and tools/wormhole_harness.js.',
].join('\n');

const diagram = {
  notes, name: 'wormhole nav',
  instances: N.map(([id, type_id, parameters, c, r]) => ({ id, type_id, parameters, position: { x: 40 + c * 240, y: 40 + r * 165 } })),
  edges: E,
};

if (require.main === module) {
  fs.writeFileSync(path.join(__dirname, '..', 'circuits', 'wormhole_nav.json'), JSON.stringify(diagram, null, 1));
  const isLogic = (i) => !['wireless_transmitter', 'accelerometer', 'gravitymeter', 'axis_rotometer', 'joystick_3d', 'switch'].includes(i.type_id);
  const radio = diagram.instances.filter((i) => i.type_id === 'wireless_transmitter').length;
  console.log(`wormhole_nav.json: ${diagram.instances.length} parts (${diagram.instances.filter(isLogic).length} logic, ${radio} radio), ${E.length} wires`);
}

module.exports = { diagram, TUNE };
