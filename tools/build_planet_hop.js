'use strict';
// Generates circuits/planet_hop_v2.json.  Run: node tools/build_planet_hop.js
// Fly it against the 1-D model:              node tools/flight_harness.js
//
// Suicide-burn autopilot. Accelerates toward the target, commits to a throttled braking
// burn at the last safe moment, and cuts the thrusters once braking has stopped the ship,
// so it never reverses away. Works from rest or with the ship already moving at enable.
//
//   a_brake    = |accelerometer| ÷ (accelerating ? thrust_ratio : 1)
//                thrust_ratio = forward ÷ reverse acceleration (0 = unknown → 1)
//   a_held     = a_brake, updated only while the command has been steady at full thrust
//                for 10 ticks (so mid-switch and throttled readings are ignored)
//   a_plan     = max(a_held + gravity, 0.01) × 0.95        gravity: + helps braking, − hurts
//   stop_dist  = v² ÷ (2 · a_plan)
//   d_plan     = distance − v · lead − standoff             lead covers sensor→thruster delay
//   decision   = d_plan > stop_dist ? +1 : −1
//   committed  = enable AND (committed OR (decision < 0 AND a_held known for 10 ticks))
//   brake      = d_plan ≤ stop_dist ? 1 : max(stop_dist ÷ d_plan, 0.5)   (≈0.95 on the curve; the
//                0.5 floor stops the last metres tapering off forever as v → 0)
//   command    = committed ? −brake : decision
//   stopped    = enable AND (stopped OR (command < 0 AND v ≤ (|accelerometer| + gravity) × cut))
//   arrived    = stopped, as an output: thrust is cut, so under gravity hand over to hover/landing
//   thruster   = stopped ? 0 : command × enable              (enable via a 10-tick Initializer)
//
// The two holds (committed, stopped) are logic feedback loops, legal in the game's tick
// model. Unwired Condition ports use the game's defaults (B = 0, True = 1, False = 0) and an
// unwired Subtractor A reads 0, so the only constants left are tuning values.
const fs = require('fs');
const path = require('path');

// [id, type_id, params, col, row]
const N = [
  // ---- inputs ----
  ['in_distance',     'slider', { value: 50000000 }, 0, 0],
  ['in_velocity',     'slider', { value: 300000 },   0, 2],
  ['in_accel',        'slider', { value: 500 },      0, 5],
  ['in_thrust_ratio', 'slider', { value: 0 },        0, 6],
  ['in_gravity',      'slider', { value: 0 },        0, 7],
  ['in_enable',       'toggle', { value: 1 },        0, 9],

  // ---- tuning constants ----
  ['tune_lead_s',     'constant', { value: 0.25 }, 2, 1],  // seconds of travel lost to the delay (safety)
  ['tune_standoff_m', 'constant', { value: 50 },   3, 1],  // stop this far short of the surface
  ['tune_cut_s',      'constant', { value: 0.15 }, 6, 12], // sensor→thruster delay (~9 ticks): cut this early
  ['tune_two_margin', 'constant', { value: 1.9 },  6, 8],  // 2 × 0.95: plan on 95% of the brakes
  ['tune_a_floor',    'constant', { value: 0.01 }, 5, 8],  // never plan on less braking than this
  ['tune_v_floor',    'constant', { value: 0.01 }, 2, 12], // avoid ÷0 in time-to-arrival
  ['tune_min_brake',  'constant', { value: 0.5 },  10, 3],  // committed braking never drops below this throttle

  // ---- distance and velocity ----
  ['dist_router',     'data_router_2', {}, 1, 0],
  ['vel_router',      'data_router_4', {}, 1, 2],
  ['vel_router_2',    'data_router_2', {}, 2, 11],
  ['v_squared',       'multiplier', {}, 2, 3],
  ['lead_m',          'multiplier', {}, 2, 2],
  ['dist_after_lead', 'subtractor', {}, 3, 0],
  ['dist_plan',       'subtractor', {}, 4, 0],
  ['d_plan_router',   'data_router_4', {}, 5, 0],

  // ---- braking acceleration ----
  ['accel_abs',       'abs', {}, 1, 5],
  ['accel_router',    'data_router_2', {}, 2, 5],
  ['ratio_router',    'data_router_2', {}, 1, 6],
  ['ratio_or_one',    'condition', { op: 0 }, 2, 6],   // ratio == 0 ? 1 : ratio
  ['ratio_if_accel',  'condition', { op: 2 }, 3, 6],   // command < 0 ? 1 : ratio
  ['a_brake',         'divider', {}, 3, 5],
  ['a_brake_router',  'data_router_2', {}, 4, 5],
  ['a_measured_pos',  'condition', { op: 3 }, 5, 6],   // a_brake > 0 ? 1 : 0  (thrusters firing)
  ['a_update',        'and', {}, 6, 6],
  ['a_held',          'memory', { mode: 0 }, 5, 5],
  ['a_held_router',   'data_router_2', {}, 6, 5],
  ['a_known',         'condition', { op: 3 }, 7, 6],   // a_held > 0 ? 1 : 0
  ['a_known_settled', 'delay', { ticks: 10 }, 8, 6],    // let the decision catch up with a new estimate
  ['a_with_gravity',  'adder', {}, 4, 8],
  ['gravity_router',  'data_router_2', {}, 1, 7],
  ['a_net_now',       'adder', {}, 6, 11],             // measured braking now, net of gravity
  ['a_floored',       'max', {}, 5, 9],
  ['two_a_plan',      'multiplier', {}, 7, 8],

  // ---- stopping distance, decision, committed braking ----
  ['stopping_distance', 'divider', {}, 8, 3],
  ['stop_router',     'data_router_4', {}, 9, 3],
  ['decision',        'condition', { op: 3 }, 10, 0],  // d_plan > stop ? 1 : −brake
  ['decision_router', 'data_router_2', {}, 11, 0],
  ['brake_ratio',     'divider', {}, 10, 2],           // stop ÷ d_plan
  ['brake_floor',     'max', {}, 11, 3],               // max(stop ÷ d_plan, min_brake)
  ['brake_level',     'condition', { op: 4 }, 11, 2],  // d_plan ≤ stop ? 1 : the above
  ['brake_cmd',       'subtractor', {}, 12, 2],        // 0 − brake_level
  ['brake_router',    'data_router_2', {}, 13, 2],
  ['wants_brake',     'condition', { op: 2 }, 12, 4],  // decision < 0 ? 1 : 0
  ['commit_now',      'and', {}, 13, 4],
  ['commit_or',       'or', {}, 14, 4],
  ['committed',       'and', {}, 15, 4],
  ['committed_router','data_router_2', {}, 16, 4],
  ['command',         'condition', { op: 0 }, 14, 0],  // committed == 0 ? decision : −brake
  ['command_router',  'data_router_4', {}, 15, 0],
  ['command_router_2','data_router_2', {}, 16, 6],
  ['command_delayed', 'delay', { ticks: 10 }, 17, 6],
  ['command_steady',  'condition', { op: 0 }, 18, 6],  // command == command 10 ticks ago ? 1 : 0

  // ---- stop hold ----
  ['v_cut',           'multiplier', {}, 7, 11],        // speed the brakes (as measured now) remove within the delay
  ['is_slow',         'condition', { op: 4 }, 8, 11],  // v ≤ v_cut ? 1 : 0  (≤ so a fully settled 0 ≤ 0 counts)
  ['is_braking',      'condition', { op: 2 }, 16, 8],  // command < 0 ? 1 : 0
  ['stop_now',        'and', {}, 17, 10],
  ['stop_or',         'or', {}, 18, 10],
  ['stopped',         'and', {}, 19, 10],
  ['stopped_router',  'data_router_4', {}, 20, 10],
  ['arrived',         'datameter', {}, 21, 10],          // 1 once stopped: hand over to hover/landing
  ['enable_init',     'initializer', { ticks: 10 }, 1, 9],
  ['enable_router',   'data_router_4', {}, 2, 9],

  // ---- output ----
  ['hold_if_stopped', 'condition', { op: 0 }, 17, 0],  // stopped == 0 ? command : 0
  ['thruster_out',    'multiplier', {}, 18, 0],

  // ---- time to arrival ----
  ['v_safe',          'max', {}, 3, 12],
  ['time_to_arrival', 'divider', {}, 4, 12],
];

const E = `
in_distance.out dist_router.in
in_velocity.out vel_router.in
vel_router.a v_squared.a
vel_router.b v_squared.b
vel_router.c lead_m.a
vel_router.d vel_router_2.in
tune_lead_s.out lead_m.b
dist_router.a dist_after_lead.a
lead_m.out dist_after_lead.b
dist_after_lead.out dist_plan.a
tune_standoff_m.out dist_plan.b
dist_plan.out d_plan_router.in

in_accel.out accel_abs.in
in_thrust_ratio.out ratio_router.in
ratio_router.a ratio_or_one.a
ratio_router.b ratio_or_one.false
ratio_or_one.out ratio_if_accel.false
command_router.c ratio_if_accel.a
accel_abs.out accel_router.in
accel_router.a a_brake.a
ratio_if_accel.out a_brake.b
a_brake.out a_brake_router.in
a_brake_router.a a_held.value
a_brake_router.b a_measured_pos.a
command_router.d command_router_2.in
command_router_2.a command_steady.a
command_router_2.b command_delayed.in
command_delayed.out command_steady.b
command_steady.out a_update.a
a_measured_pos.out a_update.b
a_update.out a_held.set
a_held.out a_held_router.in
a_held_router.a a_with_gravity.a
a_held_router.b a_known.a
in_gravity.out gravity_router.in
gravity_router.a a_with_gravity.b
a_with_gravity.out a_floored.a
tune_a_floor.out a_floored.b
a_floored.out two_a_plan.a
tune_two_margin.out two_a_plan.b

v_squared.out stopping_distance.a
two_a_plan.out stopping_distance.b
stopping_distance.out stop_router.in
d_plan_router.a decision.a
stop_router.a decision.b
brake_router.a decision.false
decision.out decision_router.in
stop_router.b brake_ratio.a
d_plan_router.b brake_ratio.b
d_plan_router.c brake_level.a
stop_router.c brake_level.b
brake_ratio.out brake_floor.a
tune_min_brake.out brake_floor.b
brake_floor.out brake_level.false
brake_level.out brake_cmd.b
brake_cmd.out brake_router.in
decision_router.a command.true
decision_router.b wants_brake.a
wants_brake.out commit_now.a
a_known.out a_known_settled.in
a_known_settled.out commit_now.b
commit_now.out commit_or.a
committed_router.b commit_or.b
commit_or.out committed.a
enable_router.c committed.b
committed.out committed_router.in
committed_router.a command.a
brake_router.b command.false
command.out command_router.in

accel_router.b a_net_now.a
gravity_router.b a_net_now.b
a_net_now.out v_cut.a
tune_cut_s.out v_cut.b
vel_router_2.a is_slow.a
v_cut.out is_slow.b
command_router.b is_braking.a
is_slow.out stop_now.a
is_braking.out stop_now.b
stop_now.out stop_or.a
stopped_router.b stop_or.b
stop_or.out stopped.a
enable_router.d stopped.b
stopped.out stopped_router.in
stopped_router.c arrived.in
in_enable.out enable_init.in
enable_init.out enable_router.in

stopped_router.a hold_if_stopped.a
command_router.a hold_if_stopped.true
hold_if_stopped.out thruster_out.a
enable_router.a thruster_out.b

vel_router_2.b v_safe.a
tune_v_floor.out v_safe.b
dist_router.b time_to_arrival.a
v_safe.out time_to_arrival.b
`.trim().split('\n').filter((l) => l.trim()).map((l) => {
  const [f, t] = l.trim().split(/\s+/);
  const [from_instance, from_port] = f.split('.');
  const [to_instance, to_port] = t.split('.');
  return { from_instance, from_port, to_instance, to_port, color: '#e9c46a' };
});

// Sanity: every wire names real blocks, and no output drives two inputs.
const ids = new Set(N.map((n) => n[0]));
const used = new Set();
for (const e of E) {
  for (const id of [e.from_instance, e.to_instance]) if (!ids.has(id)) throw new Error('unknown block ' + id);
  const k = e.from_instance + '.' + e.from_port;
  if (used.has(k)) throw new Error('output drives two inputs: ' + k);
  used.add(k);
}

const diagram = {
  instances: N.map(([id, type_id, parameters, c, r]) => ({
    id, type_id, parameters, position: { x: 40 + c * 240, y: 40 + r * 165 }, color: '#e9c46a', mirrored: false,
  })),
  edges: E, groups: [], max_per_column: 4, max_rows: 4, max_columns: 8,
};
fs.writeFileSync(path.join(__dirname, '..', 'circuits', 'planet_hop_v2.json'), JSON.stringify(diagram, null, 2) + '\n');
console.log(`planet_hop_v2.json: ${N.length} blocks (${N.filter((n) => n[1] === 'constant').length} constants), ${E.length} wires`);
