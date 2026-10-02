'use strict';
// Generates circuits/raster_sweep_v2.json.  Run: node tools/build_raster_sweep_v2.js
// Test it against the attitude model:         node tools/attitude_harness.js
//
// Closed-loop target lock by CONE PROBING. Fly by hand with a wide scanner cone until the Space Scanner sees
// the target, then press Start. The ship's heading is slow to change but the scanner's cone changes on the
// next tick, so the circuit mostly measures with the cone and moves the ship only a few times:
//
//   probe     hold still; try the 1° cone, then halve the interval between "seen" and "not seen" cone widths
//             10 times. The smallest cone that sees the target gives f = its angular distance from the nose to
//             the target's edge (±0.03°). (A body counts once any of its disk is in the cone.)
//   states    0 probe f0 · 1 nudge yaw +δ · 2 probe f1 · 3 nudge pitch +δ · 4 probe f2 ·
//             5 slew to the trilaterated centre (|C − Pi| = fi from the three probe points; δ = clamp(0.3·f0, 0.5°, 5°));
//               if the 1° cone then sees the target go on, else probe again from here (each round lands closer)
//             6 sweep yaw left until lost · 7 sweep yaw right until lost · 8 centre yaw between the edges ·
//             9–11 the same for pitch · 12 locked: hold with the 1° cone
//             state 0 jumps straight to 6 when the 1° cone already sees the target
//   seen      probing: the scanner's reading is within 5% of D0, or nearer (the scanner reports only the nearest
//             body, so a nearer one hides the target; counting it as "seen" is right when the target is the one
//             nearer the nose); farther, or the empty cone (1e20), is "not seen".
//             sweeping: a reading near D0 is "seen", farther/empty is "not seen", nearer keeps the last answer.
//   D0        the distance when Start was pressed, then tracked while the target is seen
//   θ         Σ rotometer rate × sign / 60: the heading (deg), never reset
//   hold      command = clamp(kp·(setpoint − θ) − kd·rate, ±1); kp = 6.25 / rcs, kd = 4.25 / rcs, where rcs
//             (tune_rcs) is the ship's deg/s² at full stick
//   sweeps    speed = 0.3°/s + 1.2 × distance swept per s, up to 2°/s, so a big planet's edges come quickly; both
//             directions run alike, so sensor and loop lag move both edges the same way and cancel in the centre
//   abort     joystick moved (> 0.3) or the target unseen for 10 s → back to manual
//
// Hardware: Space Scanner facing the ship's nose; RCS Controller (yaw, pitch) driven by this circuit; Joystick
// 3D yaw/pitch into this circuit (passed through in manual); a Button for Start; two Axis Rotometers, one
// upright (yaw rate) and one on its side (pitch rate).
const fs = require('fs');
const path = require('path');

const B = [];                       // [id, type_id, params]
const W = [];                       // ['id.port', 'id.port'] (one source may feed many inputs)
const block = (id, type_id, params = {}) => { B.push([id, type_id, params]); return id; };
const wire = (from, to) => W.push([from, to]);
const two = (id, type, a, b, params = {}) => { block(id, type, params); if (a) wire(a, `${id}.a`); if (b) wire(b, `${id}.b`); return id; };
const one = (id, type, src, params = {}) => { block(id, type, params); wire(src, `${id}.in`); return id; };
// Condition: (a op b) ? t : f   (op: engine encoding 0 =, 1 ≠, 2 <, 3 >, 4 ≤, 5 ≥; unwired b = 0, t = 1, f = 0)
const cond = (id, op, a, b, t, f) => {
  block(id, 'condition', { op });
  wire(a, `${id}.a`); if (b) wire(b, `${id}.b`); if (t) wire(t, `${id}.true`); if (f) wire(f, `${id}.false`);
  return id;
};
const mem = (id, value, set) => { block(id, 'memory', { mode: 0 }); wire(value, `${id}.value`); wire(set, `${id}.set`); return id; };
const acc = (id, input, reset) => { block(id, 'accumulator', { mode: 0 }); wire(input, `${id}.in`); if (reset) wire(reset, `${id}.reset`); return id; };
const out = (id) => `${id}.out`;
const EQ = 0, NE = 1, LT = 2, GT = 3, LE = 4, GE = 5;

// ---- inputs ----
block('in_scan_dist', 'slider', { value: 1e20 });   // Space Scanner distance (1e20 = nothing in the cone)
block('in_yaw_rate', 'slider', { value: 0 });       // Axis Rotometer, yaw (deg/s)
block('in_pitch_rate', 'slider', { value: 0 });     // Axis Rotometer, pitch (deg/s)
block('in_joy_yaw', 'slider', { value: 0 });        // Joystick 3D yaw, -1..1
block('in_joy_pitch', 'slider', { value: 0 });      // Joystick 3D pitch, -1..1
block('in_cone_manual', 'slider', { value: 0.4 });  // your cone setting for searching by hand (0 = 50°, 1 = 1°)
block('in_start', 'toggle', { value: 0 });          // Start button (1 while held)

// ---- tuning ----
block('tune_rcs', 'constant', { value: 20 });           // deg/s² at full stick: hold full yaw 1 s, read the yaw rotometer
block('tune_yaw_sign', 'constant', { value: 1 });       // -1 if the yaw rotometer reads negative for stick right
block('tune_pitch_sign', 'constant', { value: 1 });     // -1 if the pitch rotometer reads negative for stick up
block('tune_tol', 'constant', { value: 0.05 });         // the target: within 5% of its remembered distance
block('tune_probe_period', 'constant', { value: 18 });  // ticks per cone probe: the answer for a new cone takes 13–17 ticks
block('tune_probe_due', 'constant', { value: 17 });     // to come back (bisection → cone → scanner → here); read it at tick 17
block('tune_probe_last', 'constant', { value: 11 });    // probe 0 at 1°, then 10 halvings (±0.03°)
block('tune_nudge_frac', 'constant', { value: 0.3 });   // nudge = 30% of f0 ...
block('tune_nudge_min', 'constant', { value: 0.5 });    // ... at least 0.5° ...
block('tune_nudge_max', 'constant', { value: 5 });      // ... at most 5°
block('tune_sweep_base', 'constant', { value: 0.005 }); // sweep: 0.005°/tick (0.3°/s) ...
block('tune_sweep_grow', 'constant', { value: 0.02 });  // ... + 2% of the distance swept, per tick ...
block('tune_sweep_max', 'constant', { value: 1 / 30 });  // ... up to 2°/s
block('tune_settle_err', 'constant', { value: 0.05 });  // settled: heading error below 0.05° ...
block('tune_settle_rate', 'constant', { value: 0.5 });  // ... rotation below 0.5 deg/s ...
block('tune_settle_ticks', 'constant', { value: 20 });  // ... for 20 ticks
block('tune_blank', 'constant', { value: 30 });         // and never in the first 30 ticks of a state
block('tune_settle_timeout', 'constant', { value: 240 });// a move that has not settled after 4 s is accepted
block('tune_lost_ticks', 'constant', { value: 600 });   // give up after 10 s without the target
block('tune_abort', 'constant', { value: 0.3 });        // joystick deflection that takes control back
block('k_dt', 'constant', { value: 1 / 60 });
block('k_kp_num', 'constant', { value: 6.25 });       // ω² with ω = 2.5 rad/s
block('k_kd_num', 'constant', { value: 4.25 });       // 2ζω with ζ = 0.85
block('k_one', 'constant', { value: 1 });
block('k_neg_one', 'constant', { value: -1 });
block('k_half', 'constant', { value: 0.5 });
block('k_empty', 'constant', { value: 1e19 });
block('k_50', 'constant', { value: 50 });
block('k_49', 'constant', { value: 49 });
block('k_skip', 'constant', { value: 6 });
block('k_done', 'constant', { value: 12 });
for (const k of [2, 3, 4, 5, 6, 7, 8, 9, 10, 11]) block(`k_${k}`, 'constant', { value: k });
const K = (k) => (k === 0 ? null : out(k === 1 ? 'k_one' : `k_${k}`));

// ---- heading from the rotometers ----
two('w_yaw', 'multiplier', out('in_yaw_rate'), out('tune_yaw_sign'));
two('w_pitch', 'multiplier', out('in_pitch_rate'), out('tune_pitch_sign'));
two('dyaw', 'multiplier', out('w_yaw'), out('k_dt'));
two('dpitch', 'multiplier', out('w_pitch'), out('k_dt'));
acc('theta_yaw', out('dyaw'));
acc('theta_pitch', out('dpitch'));

// ---- what the scanner sees ----
cond('dist_valid', LT, out('in_scan_dist'), out('k_empty'));
two('dist_diff', 'subtractor', out('in_scan_dist'), out('d0'));
one('dist_absdiff', 'abs', out('dist_diff'));
two('d0_tol', 'multiplier', out('d0'), out('tune_tol'));
cond('dist_match', LE, out('dist_absdiff'), out('d0_tol'));
two('det_raw', 'and', out('dist_valid'), out('dist_match'));       // exactly the target
two('d0_far', 'adder', out('d0'), out('d0_tol'));
cond('not_farther', LE, out('in_scan_dist'), out('d0_far'));
two('probe_det', 'and', out('dist_valid'), out('not_farther'));    // the target, or something nearer hiding it
two('d0_near', 'subtractor', out('d0'), out('d0_tol'));
cond('unmasked', GE, out('in_scan_dist'), out('d0_near'));
two('det_set', 'and', out('unmasked'), out('k_one'));             // same block count as det_raw, so both line up
mem('det', out('det_raw'), out('det_set'));                        // sweeps: nearer body → keep the last answer
mem('d0', out('in_scan_dist'), out('d0_set'));                     // the target's distance (tracked)
two('d0_set', 'or', out('not_auto'), out('det_raw'));

// ---- Start, auto, abort ----
// auto is a Memory: an OR/AND feedback latch only circulates a short pulse in the tick model. Its value and
// set inputs reach it through the same number of blocks, so releasing Start never stores a 0.
two('auto_val', 'and', out('in_start'), out('no_abort'));
two('auto_set', 'or', out('in_start'), out('abort'));
mem('auto', out('auto_val'), out('auto_set'));
one('not_auto', 'not', out('auto'));
one('joy_yaw_abs', 'abs', out('in_joy_yaw'));
one('joy_pitch_abs', 'abs', out('in_joy_pitch'));
cond('joy_yaw_big', GT, out('joy_yaw_abs'), out('tune_abort'));
cond('joy_pitch_big', GT, out('joy_pitch_abs'), out('tune_abort'));
two('joy_active', 'or', out('joy_yaw_big'), out('joy_pitch_big'));
two('nodet_reset', 'or', out('probe_det'), out('not_auto'));
acc('nodet_count', out('k_one'), out('nodet_reset'));
cond('lost', GT, out('nodet_count'), out('tune_lost_ticks'));
two('abort', 'or', out('joy_active'), out('lost'));
one('no_abort', 'not', out('abort'));

// ---- state ----
two('s_reset', 'or', out('not_auto'), out('restart'));
acc('s_count', out('adv_amount'), out('s_reset'));
cond('done', GE, out('s_count'), out('k_done'));
for (let k = 0; k < 12; k++) cond(`is_${k}`, EQ, out('s_count'), K(k));
one('s_prev', 'delay', out('s_count'), { ticks: 1 });             // one block more than the comparator's other input
cond('changed', NE, out('s_count'), out('s_prev'));
one('changed_late', 'delay', out('changed'), { ticks: 12 });      // state-entry moves wait for their inputs to settle
const entry = (k) => two(`entry_${k}`, 'and', out('changed_late'), out(`is_${k}`));
for (const k of [1, 3, 5, 8, 11]) entry(k);

// ---- cone probing (states 0, 2, 4) ----
two('probe_st1', 'or', out('is_0'), out('is_2'));
two('probe_st', 'or', out('probe_st1'), out('is_4'));
two('probing', 'and', out('probe_st'), out('auto'));
one('not_probing', 'not', out('probing'));
acc('probe_tick', out('k_one'), out('not_probing'));            // free-running: a probe every tune_probe_period ticks
two('pt_phase', 'mod', out('probe_tick'), out('tune_probe_period'));
cond('pt_due', EQ, out('pt_phase'), out('tune_probe_due'));
two('sample', 'and', out('pt_due'), out('probing'));               // one tick: read the answer for this cone
acc('probe_k', out('sample'), out('not_probing'));                 // probes done in this measurement
// bisection on the scanner's input v (0 = 50° cone, 1 = 1°): v_in = largest v that saw it, v_out = smallest that did not
two('v_sum', 'adder', out('v_in'), out('v_out'));
two('v_mid', 'multiplier', out('v_sum'), out('k_half'));
cond('v_probe', EQ, out('probe_k'), null, null, out('v_mid'));          // probe 0: the 1° cone (an unwired True reads 1)
// the switch comes from not_probing, like the set path below, so value and set change on the same tick
cond('v_in_val', EQ, out('not_probing'), null, out('v_probe'));   // probing ? v_probe : 0 (an unwired False reads 0)
cond('v_out_val', EQ, out('not_probing'), out('k_one'), null, out('v_probe'));   // not probing ? 1 : v_probe
two('hit', 'and', out('sample'), out('probe_det'));
one('no_probe_det', 'not', out('probe_det'));
two('miss', 'and', out('sample'), out('no_probe_det'));
two('v_in_set', 'or', out('not_probing'), out('hit'));
two('v_out_set', 'or', out('not_probing'), out('miss'));
mem('v_in', out('v_in_val'), out('v_in_set'));                     // starts at 0 (50°)
mem('v_out', out('v_out_val'), out('v_out_set'));                  // starts at 1 (1°)
cond('pk_last', EQ, out('probe_k'), out('tune_probe_last'));
two('meas_done', 'and', out('sample'), out('pk_last'));
two('c_in49', 'multiplier', out('v_in'), out('k_49'));
two('c_in', 'subtractor', out('k_50'), out('c_in49'));             // smallest cone that saw it, degrees
two('f_now', 'multiplier', out('c_in'), out('k_half'));            // f = that cone / 2
for (const [k, st] of [[0, 'is_0'], [1, 'is_2'], [2, 'is_4']]) {
  two(`f${k}_set`, 'and', out('meas_done'), out(st));
  mem(`f${k}`, out('f_now'), out(`f${k}_set`));
}
// already inside the 1° cone at the first probe of state 0: skip to the final centring
cond('pk_zero', EQ, out('probe_k'), null);
two('first_hit', 'and', out('hit'), out('pk_zero'));
two('close_skip', 'and', out('first_hit'), out('is_0'));

// ---- nudge size and the slew from the three probes ----
two('nudge_raw', 'multiplier', out('f0'), out('tune_nudge_frac'));
two('nudge_lo', 'max', out('nudge_raw'), out('tune_nudge_min'));
two('nudge', 'min', out('nudge_lo'), out('tune_nudge_max'));
// target centre C from |C − Pi| = fi (exact for a small body; a big one lands inside its disk, which is enough):
//   Cx = (f0² − f1² + δ²) / 2δ        Cy = (f0² − f2²) / 2δ + δ − Cx        slew (from P2) = C − (δ, δ)
two('f0sq', 'multiplier', out('f0'), out('f0'));
two('f1sq', 'multiplier', out('f1'), out('f1'));
two('f2sq', 'multiplier', out('f2'), out('f2'));
two('nudge_sq', 'multiplier', out('nudge'), out('nudge'));
two('two_nudge', 'multiplier', out('nudge'), out('k_2'));
two('d01', 'subtractor', out('f0sq'), out('f1sq'));
two('cx_num', 'adder', out('d01'), out('nudge_sq'));
two('cx', 'divider', out('cx_num'), out('two_nudge'));
two('d02', 'subtractor', out('f0sq'), out('f2sq'));
two('cy_a', 'divider', out('d02'), out('two_nudge'));
two('cy_b', 'adder', out('cy_a'), out('nudge'));
two('cy', 'subtractor', out('cy_b'), out('cx'));
two('slew_yaw', 'subtractor', out('cx'), out('nudge'));
two('slew_pitch', 'subtractor', out('cy'), out('nudge'));

// ---- the hold point: heading at Start + every nudge, slew and centring move (accumulated) ----
function axis(name, nudgeEntry, centreEntry, flagL, flagR, slew) {
  mem(`${name}_base`, out(`theta_${name}`), out('not_auto'));      // follows the heading in manual
  two(`${name}_m1`, 'multiplier', out('nudge'), out(nudgeEntry));
  two(`${name}_m2`, 'multiplier', out(slew), out('entry_5'));
  two(`${name}_to_centre`, 'subtractor', out(`${name}_centre`), out(`${name}_hold`));
  two(`${name}_m3`, 'multiplier', out(`${name}_to_centre`), out(centreEntry));
  two(`${name}_m12`, 'adder', out(`${name}_m1`), out(`${name}_m2`));
  two(`${name}_moves`, 'adder', out(`${name}_m12`), out(`${name}_m3`));
  acc(`${name}_acc`, out(`${name}_moves`), out('not_auto'));
  two(`${name}_hold`, 'adder', out(`${name}_base`), out(`${name}_acc`));
  // sweeps (final centring): accelerating ramps away from the hold point, cleared outside their phase
  for (const [side, flag, sign] of [['L', flagL, -1], ['R', flagR, 1]]) {
    one(`${name}_off${side}_abs`, 'abs', out(`${name}_off${side}`));
    two(`${name}_off${side}_grow`, 'multiplier', out(`${name}_off${side}_abs`), out('tune_sweep_grow'));
    two(`${name}_off${side}_rate_raw`, 'adder', out(`${name}_off${side}_grow`), out('tune_sweep_base'));
    two(`${name}_off${side}_rate`, 'min', out(`${name}_off${side}_rate_raw`), out('tune_sweep_max'));
    if (sign < 0) {
      two(`${name}_off${side}_flagneg`, 'subtractor', null, out(flag));
      two(`${name}_off${side}_in`, 'multiplier', out(`${name}_off${side}_rate`), out(`${name}_off${side}_flagneg`));
    } else {
      two(`${name}_off${side}_in`, 'multiplier', out(`${name}_off${side}_rate`), out(flag));
    }
    one(`${name}_not${side}`, 'not', out(flag));
    acc(`${name}_off${side}`, out(`${name}_off${side}_in`), out(`${name}_not${side}`));
  }
  two(`${name}_sp1`, 'adder', out(`${name}_hold`), out(`${name}_offL`));
  two(`${name}_sp`, 'adder', out(`${name}_sp1`), out(`${name}_offR`));
  // edges: the falling edge of `det`, only on the side the sweep is heading for
  cond(`${name}_left`, LT, out(`theta_${name}`), out(`${name}_hold`));
  cond(`${name}_right`, GT, out(`theta_${name}`), out(`${name}_hold`));
  two(`${name}_fallL`, 'and', out('fall'), out(flagL));
  two(`${name}_fallR`, 'and', out('fall'), out(flagR));
  two(`${name}_setL`, 'and', out(`${name}_fallL`), out(`${name}_left`));
  two(`${name}_setR`, 'and', out(`${name}_fallR`), out(`${name}_right`));
  mem(`${name}_edgeL`, out(`theta_${name}`), out(`${name}_setL`));
  mem(`${name}_edgeR`, out(`theta_${name}`), out(`${name}_setR`));
  two(`${name}_edge_sum`, 'adder', out(`${name}_edgeL`), out(`${name}_edgeR`));
  two(`${name}_centre`, 'multiplier', out(`${name}_edge_sum`), out('k_half'));
  // hold loop: command = clamp(kp·(setpoint − θ) − kd·rate, ±1)
  two(`${name}_err`, 'subtractor', out(`${name}_sp`), out(`theta_${name}`));
  two(`${name}_kp_e`, 'multiplier', out(`${name}_err`), out('kp'));
  two(`${name}_kd_w`, 'multiplier', out(`w_${name}`), out('kd'));
  two(`${name}_u`, 'subtractor', out(`${name}_kp_e`), out(`${name}_kd_w`));
  two(`${name}_u_hi`, 'min', out(`${name}_u`), out('k_one'));
  two(`${name}_u_c`, 'max', out(`${name}_u_hi`), out('k_neg_one'));
  one(`${name}_err_abs`, 'abs', out(`${name}_err`));
  one(`${name}_w_abs`, 'abs', out(`w_${name}`));
}
two('kp', 'divider', out('k_kp_num'), out('tune_rcs'));
two('kd', 'divider', out('k_kd_num'), out('tune_rcs'));
one('fall_not', 'not', out('det'));
one('fall_prev', 'delay', out('det'), { ticks: 2 });              // NOT path + 1 = delay path: a 1-tick falling edge
two('fall', 'and', out('fall_not'), out('fall_prev'));
for (const k of [6, 7, 9, 10]) two(`sw_${k}`, 'and', out(`is_${k}`), out('auto'));
axis('yaw', 'entry_1', 'entry_8', 'sw_6', 'sw_7', 'slew_yaw');
axis('pitch', 'entry_3', 'entry_11', 'sw_9', 'sw_10', 'slew_pitch');

// ---- settling (nudges, slew, centring) ----
two('err_sum', 'adder', out('yaw_err_abs'), out('pitch_err_abs'));
two('w_sum', 'adder', out('yaw_w_abs'), out('pitch_w_abs'));
cond('err_ok', LT, out('err_sum'), out('tune_settle_err'));
cond('w_ok', LT, out('w_sum'), out('tune_settle_rate'));
two('settled_raw', 'and', out('err_ok'), out('w_ok'));
two('st_a', 'or', out('is_1'), out('is_3'));
two('st_b', 'or', out('is_5'), out('is_8'));
two('st_ab', 'or', out('st_a'), out('st_b'));
two('st_all', 'or', out('st_ab'), out('is_11'));
two('settle_phase', 'and', out('st_all'), out('auto'));
// ignore the first 30 ticks of a state: its move is applied 12 ticks in and takes a few more to show in the error
acc('since_change', out('k_one'), out('changed'));
cond('blanked', GT, out('since_change'), out('tune_blank'));
two('settle_ok_time', 'and', out('settle_phase'), out('blanked'));
two('settle_on', 'and', out('settled_raw'), out('settle_ok_time'));
one('settle_off', 'not', out('settle_on'));
acc('settle_count', out('k_one'), out('settle_off'));
cond('settle_hit', EQ, out('settle_count'), out('tune_settle_ticks'));   // one tick when the count reaches N
// ... or, if a move never settles (an RCS deadband stops the ship a little short), accept it after 4 s
cond('settle_late', EQ, out('since_change'), out('tune_settle_timeout'));
two('settle_late_on', 'and', out('settle_late'), out('settle_phase'));
two('settle_done', 'or', out('settle_hit'), out('settle_late_on'));

// ---- advancing ----
// after the slew (state 5): on if the 1° cone sees the target, else probe again from here
one('no_det', 'not', out('det'));
two('slew_end', 'and', out('settle_done'), out('is_5'));
two('restart', 'and', out('slew_end'), out('no_det'));
one('not_restart', 'not', out('restart'));
two('edge_yaw', 'or', out('yaw_setL'), out('yaw_setR'));
two('edge_pitch', 'or', out('pitch_setL'), out('pitch_setR'));
two('edge_any', 'or', out('edge_yaw'), out('edge_pitch'));
two('settle_adv', 'and', out('settle_done'), out('not_restart'));
two('adv_a', 'or', out('meas_done'), out('settle_adv'));
two('adv1', 'or', out('adv_a'), out('edge_any'));
two('skip_amt', 'multiplier', out('close_skip'), out('k_skip'));
two('adv_amount', 'adder', out('adv1'), out('skip_amt'));

// ---- outputs ----
cond('cone_auto', EQ, out('probing'), out('k_one'), out('v_probe'), out('k_one'));   // the 1° cone except while probing
cond('rcs_yaw', EQ, out('auto'), out('k_one'), out('yaw_u_c'), out('in_joy_yaw'));
cond('rcs_pitch', EQ, out('auto'), out('k_one'), out('pitch_u_c'), out('in_joy_pitch'));
cond('cone_cmd', EQ, out('auto'), out('k_one'), out('cone_auto'), out('in_cone_manual'));
two('locked_and', 'and', out('done'), out('det'));
one('locked', 'datameter', out('locked_and'));                    // 1 = centred with the 1° cone on the target
one('progress', 'datameter', out('s_count'));                     // state 0..12 (see the header)

// ---- resolve fan-out: the game lets an output feed one input, so add Data Routers (balanced trees,
// so every copy of a signal arrives on the same tick) ----
const ids = new Set(B.map((b) => b[0]));
for (const [f, t] of W) for (const p of [f, t]) if (!ids.has(p.split('.')[0])) throw new Error(`unknown block in wire ${f} -> ${t}`);
const bySrc = new Map();
for (const [f, t] of W) { if (!bySrc.has(f)) bySrc.set(f, []); bySrc.get(f).push(t); }
const edges = [];
const edge = (f, t) => {
  const [fi, fp] = f.split('.'), [ti, tp] = t.split('.');
  edges.push({ from_instance: fi, from_port: fp, to_instance: ti, to_port: tp, color: '#7aa2f7' });
};
const PORTS4 = ['a', 'b', 'c', 'd'];
const typeOf = new Map(B.map(([id, type]) => [id, type]));
for (const [src, targets] of bySrc) {
  if (targets.length === 1) { edge(src, targets[0]); continue; }
  const base = src.split('.')[0];
  if (typeOf.get(base) === 'constant' && base.startsWith('k_')) {
    // a fixed constant is cheaper copied than routed: one copy per input, no added delay. (tune_* values are
    // routed instead, so each setting stays one block to edit.)
    const params = B.find((x) => x[0] === base)[2];
    targets.forEach((t, i) => {
      const id = i === 0 ? base : block(`${base}_${i + 1}`, 'constant', { ...params });
      edge(`${id}.out`, t);
    });
    continue;
  }
  if (targets.length <= 4) {
    const r = block(`${base}_fan`, targets.length === 2 ? 'data_router_2' : 'data_router_4');
    edge(src, `${r}.in`);
    targets.forEach((t, i) => edge(`${r}.${PORTS4[i]}`, t));
    continue;
  }
  if (targets.length > 16) throw new Error(`${src} feeds ${targets.length} inputs (max 16)`);
  const groups = [];
  for (let i = 0; i < targets.length; i += 4) groups.push(targets.slice(i, i + 4));
  const top = block(`${base}_fan`, groups.length <= 2 ? 'data_router_2' : 'data_router_4');
  edge(src, `${top}.in`);
  groups.forEach((g, gi) => {
    const r = block(`${base}_fan${gi + 1}`, g.length <= 2 ? 'data_router_2' : 'data_router_4');
    edge(`${top}.${PORTS4[gi]}`, `${r}.in`);
    g.forEach((t, i) => edge(`${r}.${PORTS4[i]}`, t));
  });
}

// ---- layout: columns by signal-flow depth (feedback edges ignored), rows in order ----
const depth = new Map(B.map(([id]) => [id, 0]));
for (let pass = 0; pass < 40; pass++) {
  let changed = false;
  for (const e of edges) {
    const d = depth.get(e.from_instance) + 1;
    if (d > depth.get(e.to_instance) && d < 40) { depth.set(e.to_instance, d); changed = true; }
  }
  if (!changed) break;
}
const rows = new Map();
const diagram = {
  instances: B.map(([id, type_id, parameters]) => {
    const c = depth.get(id), r = rows.get(c) || 0;
    rows.set(c, r + 1);
    return { id, type_id, parameters, position: { x: 40 + c * 240, y: 40 + r * 150 }, color: '#7aa2f7', mirrored: false };
  }),
  edges, groups: [], max_per_column: 4, max_rows: 4, max_columns: 8,
};
fs.writeFileSync(path.join(__dirname, '..', 'circuits', 'raster_sweep_v2.json'), JSON.stringify(diagram, null, 2) + '\n');
const routers = B.filter((b) => b[1].startsWith('data_router')).length;
console.log(`raster_sweep_v2.json: ${B.length} blocks (${B.filter((b) => b[1] === 'constant').length} constants, ${routers} routers), ${edges.length} wires`);
