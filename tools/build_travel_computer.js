'use strict';
// Generates circuits/travel_computer.json.  Run: node tools/build_travel_computer.js
// Fly it against the 1-D model:          node tools/travel_harness.js
//
// Travel computer: flies to the target the Space Scanner sees ahead and stops a set distance short of it, with reverse
// thrusters weaker than the forward ones, Small Solid Fuel Thrusters (SRBs) as a first stage and the target's gravity
// allowed for, on trips of 250,000 km or more. Built for the user's ship (their SHIP RADIOS sheet, 2026-10-05):
// 13,979,000 N forward including 6 SRBs (6 × 950,000), so 8,279,000 N on the mains, and 4,374,000 N reverse. Most of
// it is fuel engines: forward 2 Small Fuel (10 s to respond) and 1 Medium Fuel (20 s) beside 3 electrics, reverse 2
// Small Fuel beside 3 electrics.
//
//   d         FWD DIST (ch 30, Space Scanner on the nose): surface distance; 1e20 when it sees nothing, and then d_plan
//             counts as 0 ("hold here"): it never accelerates blind, nor lights the SRBs
//   v         Z SPEED (ch 23, Velocity Meter, Directional, facing forward): + closing
//   standoff  10 m · 10^(6 · lever): 10 m (lever 0) to 10,000 km (lever 1), log scale, shown in metres on a Datameter
//             (STANDOFF M), which bpgen keeps upright with nothing above it, so it stays in view
//   d_plan    d − standoff − v · lead
//   measure   from Autopilot on: meas_q (7.5%) throttle until burn_ticks, then 0 until meas_ticks, each long enough for
//             the slowest engine (spool_s, the Medium Fuel's 20 s) to reach it before a window. Δv over a
//             Differentiator's 20 ticks, held at the end of each (a Memory each), gives a_fwd = (Δv_burn − Δv_coast) ·
//             3 ÷ meas_q: gravity, and any support that lasts (a hover held by other thrusters), cancel whichever way
//             they point. The SRBs are not lit yet and still on board, so the ship is at its heaviest: every later
//             estimate errs safe. 7.5% keeps a light ship gentle (64 t: 9.7 m/s²) and needs no dead zone (the game's
//             thruster input only clamps, SCTick_Thruster_InPort); but it cannot lift a ship off the ground to measure
//             it, so it is engaged in space or hovering. Before: 21.5 s at full, which pushes a 64 t ship at 129 m/s²
//             (and a 2 s burn ended long before the fuel engines were up: it read a sixteenth of the braking).
//   a_brk     margin · a_fwd ÷ THRUST RATIO: the braking it plans on. THRUST RATIO is a Constant, forward ÷ reverse
//             thrust of the mains (SRBs left out), set in game; 0 makes a_brk 0 and the ship sits still (÷ 0 is 0)
//   MAX ACCEL a Constant, set in game: the game strains a joint when a part's velocity changes by over 0.173 m/s in a
//             tick (a net 10.39 m/s², gravity in free fall included) by 0.22 · mass · Δv², however smoothly the thrust
//             got there (the engines ramp anyway: electrics 0.25–0.95 s, fuel 10–20 s, SRBs 5 s). So the speed loop's
//             wanted net acceleration is held within ± MAX ACCEL, and the profile plans braking at most at
//             plan_frac · MAX ACCEL, leaving the loop room to correct.
//   g_avg     the target's mean pull over the rest of the brake: g · r ÷ r_s for an inverse-square well (exact: the
//             work GM (1/r_s − 1/r) over the D = r − r_s it is done across), with r the distance to the target's centre
//             = 2 g v ÷ (dg/dt) (g = GM / r², so dg/dt = 2 g v / r) and r_s = r − D. Clamped to 1..1000 × g: before the
//             ship is moving, or while the pull it feels comes from behind (a planet it is leaving: g falls as it
//             closes), it falls back to the pull it feels now. Planning on the pull it felt at the turnover instead
//             (0.45 m/s² 1,090 km out, rising to 9.8 at the surface) hit at 640 m/s.
//   a_net     min(max(a_brk − g_avg, 0.5), plan_frac · MAX ACCEL): the braking it plans on, net of the target's pull
//   v_prof    min(√(2 · a_net · max(d_plan, 0)), k_hold · d_plan): the closing speed it can still stop from; the linear
//             term takes over in the last metres and turns negative past the standoff, so it holds station there
//   g_ff      the pull along the line of flight, for the thrust: ± g, − while the pull comes from behind (a planet it
//             is leaving). r = g v ÷ Δg is positive when the source is ahead, either way it moves; the first tick
//             with r > 0 while closing faster than ahead_v latches + (an Accumulator counts them; reset with
//             Autopilot off). It starts at −, which costs a moment's error when the pull is ahead. Counting the
//             pull as ahead regardless, under MAX ACCEL it thrust backward off a planet beneath it (8 − 9.8) and fell
//             in; reading it at any speed, it flipped as the ship stopped falling and turned (Δg lags v) and fell
//             again.
//   thrust    Autopilot ? (flying ? sat(t ÷ (t ≥ 0 ? a_meas : a_brk)) : 7.5% or 0) : 0, t = clamp(k_speed · (v_prof − v),
//             ± MAX ACCEL) − g_ff: the net closing acceleration it wants, less the pull along the line,
//             over the engines that give it (a_meas = margin · a_fwd: forward comes out 1/margin strong, part of the
//             peaks' ~25%). −1..1 on THRUST CTL (1): forward thrusters read it as it is, reverse ones with "Reversed
//             Input" on. Flying starts fly_delay ticks after the measurement is held, once the held value has reached
//             the command and the SRBs' test: before, both still work from its 0 (the SRBs lit on that race, and a light
//             ship took a few ticks of full thrust). The fuel engines' 10–20 s response needs no slower loop: small
//             corrections change the throttle slower than they can follow, and the electrics take the quick part.
//   SRB       SOLID IGNITE (35) = ignited: latched once flying, the target in sight, and t > (a_fwd + a_srb) (srb_k:
//             a_srb = srb_ratio · a_fwd, the user's 6 SRBs against their mains): the wanted acceleration takes the mains
//             and the SRBs at full, so with MAX ACCEL set, only where both fit under it (the user's ship: from about
//             1,750 t at MAX ACCEL 8; they cannot be throttled, so on a lighter ship they would break the limit alone),
//             and never in the braking or the hold. SOLID EJECT (36) = ejected: latched once ignited and (t < 0: braking
//             must start, or burnout srb_ticks after ignition, or Autopilot off). Ejecting is the only way to end their
//             thrust. Neither latch resets: SRBs light once and leave once (a new flight needs a fresh Fly Mode)
const fs = require('fs');
const path = require('path');

const num = (k, d) => (process.env[k] === undefined ? d : Number(process.env[k]));
const TUNE = {
  thrust_ratio: num('THRUST_RATIO', 8279000 / 4374000),   // forward ÷ reverse thrust of the mains, SRBs left out (the
                                       // THRUST RATIO Constant's value; the user's ship: 8,279,000 ÷ 4,374,000)
  spool_s: num('SPOOL_S', 20),         // s: the slowest main or reverse engine's acceleration time (Medium Fuel)
  max_accel: num('MAX_ACCEL', 8),      // m/s²: the MAX ACCEL Constant's value, the net acceleration it keeps to (peaks
                                       // run ~25% over: 8 peaks at 10.0, under the 10.39 where the game strains joints)
  plan_frac: 0.8,                      // the profile plans braking at most at this share of MAX ACCEL
  srb_ratio: 5700000 / 8279000,        // the SRBs' thrust ÷ the mains' (lit only if both at full fit under MAX ACCEL)
  meas_q: 0.075,                       // the measuring throttle (then 0): gentle on a light ship (64 t: 9.7 m/s²)
  lead_s: num('LEAD_S', 1),            // s of travel planned for the signal delay and the thrusters' spool
  margin: num('MARGIN', 0.9),          // plan braking on this share of the reverse thrust
  k_speed: num('K_SPEED', 1.5),        // 1/s: wanted acceleration per m/s off the profile
  k_hold: num('K_HOLD', 0.5),          // 1/s: speed per metre of d_plan in the last metres (and past the standoff)
  a_min: num('A_MIN', 0.5),            // m/s²: the least net braking the profile plans on
  diff_ticks: 20,                      // the measuring Differentiator's interval
  ahead_v: 20,                         // m/s: the pull's direction is read only while closing faster than this: as v
                                       // turns, Δg (half a second) still shows the old trend, and r flips falsely
  fly_delay: 14,                       // ticks from the measurement's hold to flying: the latched value's way to the
                                       // thrust command and the SRBs' test (before, both work from its 0)
  burn_ticks: 0, meas_ticks: 0,        // meas_q throttle until burn_ticks after Autopilot on (the slowest engine's
                                       // spool up to it, then a window), 0 until meas_ticks (its spool down, then a
                                       // window); then it flies. Set from spool_s below.
  srb_ticks: 60 * 1008,                // the SRBs' 1000 s burn, their 1 s ignition and the 5 s ramps, then eject
  standoff_min: 10, standoff_max: 10e6,   // m, the lever's ends (log scale)
};
TUNE.burn_ticks = num('BURN_TICKS', Math.round(60 * (TUNE.spool_s * TUNE.meas_q + 1.5)));
TUNE.meas_ticks = num('MEAS_TICKS', TUNE.burn_ticks + Math.round(60 * (TUNE.spool_s * TUNE.meas_q + 1.2)));
const LN = (x) => Math.log(x);
// margin · a_fwd per unit of (Δv_burn − Δv_coast) over diff_ticks: a_fwd = (60 / diff_ticks) / meas_q of it
const BRK = TUNE.margin * (60 / TUNE.diff_ticks) / TUNE.meas_q;
// mains and SRBs at full, per unit of a_meas (margin · a_fwd)
const SRB_K = (1 + TUNE.srb_ratio) / TUNE.margin;

// [id, type_id, params, col, row]
const N = [
  // ---- inputs (local parts become cable stubs in the blueprint; radio is received here) ----
  ['autopilot',     'switch', { out: 0 }, 0, 0],
  ['standoff',      'slider', { value: 0.3 }, 0, 4],                  // lever 0..1
  ['gravitymeter',  'gravitymeter', { gravity: 0 }, 0, 2],
  ['rx_dist',       'wireless_transmitter', { channel: 30, label: 'FWD DIST' }, 0, 5],
  ['rx_vz',         'wireless_transmitter', { channel: 23, label: 'Z SPEED' }, 0, 7],

  // ---- Autopilot, timer, measuring burn ----
  ['auto_r',        'data_router_4', {}, 1, 0],
  ['off',           'condition', { op: 4 }, 2, 0],                     // Autopilot ≤ 0 ? 1 : 0
  ['off_r',         'data_router_4', {}, 3, 0],
  ['timer',         'accumulator', { mode: 0 }, 2, 1],                 // ticks since Autopilot on
  ['timer_r',       'data_router_4', {}, 3, 1],
  ['meas_done',     'remapper', { in_min: TUNE.meas_ticks - 1, in_max: TUNE.meas_ticks, out_min: 0, out_max: 1 }, 4, 1],
  ['fly_on',        'remapper', { in_min: TUNE.meas_ticks + TUNE.fly_delay - 1, in_max: TUNE.meas_ticks + TUNE.fly_delay, out_min: 0, out_max: 1 }, 4, 3],
  ['fly_r',         'data_router_2', {}, 5, 1],
  ['coast',         'remapper', { in_min: TUNE.burn_ticks - 1, in_max: TUNE.burn_ticks, out_min: 0, out_max: 1 }, 4, 2],
  ['burn_level',    'remapper', { in_min: TUNE.burn_ticks - 1, in_max: TUNE.burn_ticks, out_min: TUNE.meas_q, out_max: 0 }, 4, 0],
  ['phase',         'condition', { op: 1 }, 21, 1],                    // flying ≠ 0 ? thr : measuring throttle
  ['thrust',        'condition', { op: 1 }, 22, 1],                    // Autopilot ≠ 0 ? that : 0
  ['tx_thrust',     'wireless_transmitter', { channel: 1, label: 'THRUST CTL' }, 23, 1],

  // ---- the measurement: Δv at full and at half throttle ----
  ['vz_r',          'data_router_4', {}, 1, 7],
  ['dvz',           'differentiator', { interval: TUNE.diff_ticks, simulate: 0 }, 2, 8],
  ['dvz_r',         'data_router_2', {}, 3, 8],
  ['m_full',        'memory', { mode: 1 }, 5, 2],                      // Δv as the measuring burn ends
  ['m_sub',         'subtractor', {}, 6, 2],                           // − Δv as the coast ends
  ['m_diff',        'memory', { mode: 1 }, 7, 2],                      // held once measured
  ['a_meas',        'remapper', { in_min: 0.5 / BRK, in_max: 1e4, out_min: 0.5, out_max: 1e4 * BRK }, 8, 1],   // margin · a_fwd
  ['am_r',          'data_router_4', {}, 9, 1],
  ['srb_k',         'remapper', { in_min: 0, in_max: 1e4, out_min: 0, out_max: 1e4 * SRB_K }, 10, 1],   // a_fwd + a_srb
  ['thrust_ratio',  'constant', { value: +TUNE.thrust_ratio.toFixed(4), visible: true }, 7, 0],   // THRUST RATIO: set in game
  ['a_brk',         'divider', {}, 8, 2],                               // ÷ thrust ratio
  ['a_brk_r',       'data_router_2', {}, 9, 2],
  ['max_accel',     'constant', { value: TUNE.max_accel, visible: true }, 13, 0],   // MAX ACCEL: set in game
  ['max_r',         'data_router_4', {}, 14, 0],
  ['neg_max',       'subtractor', {}, 15, 0],                           // 0 − MAX ACCEL
  ['plan_cap',      'remapper', { in_min: 0, in_max: 1e4, out_min: 0, out_max: 1e4 * TUNE.plan_frac }, 15, 1],

  // ---- the target's pull over the rest of the brake ----
  ['grav_r',        'data_router_4', {}, 1, 3],
  ['gv',            'multiplier', {}, 4, 3],                            // g · v
  ['dg',            'differentiator', { interval: 30, simulate: 0 }, 2, 3],   // Δg over half a second = ġ / 2
  ['r_est',         'divider', {}, 5, 3],                               // r = 2 g v ÷ ġ = g v ÷ Δg
  ['r_r',           'data_router_4', {}, 6, 3],
  ['vz_r2',         'data_router_2', {}, 2, 9],
  ['fast',          'remapper', { in_min: TUNE.ahead_v - 1, in_max: TUNE.ahead_v, out_min: 0, out_max: 1 }, 3, 9],   // v > ahead_v
  ['ahead',         'condition', { op: 3 }, 7, 2],                      // closing fast and r > 0 (the pull is ahead)
  ['ahead_n',       'accumulator', { mode: 0 }, 8, 2],                  // ticks of that since Autopilot on
  ['g_r2',          'data_router_2', {}, 2, 2],
  ['neg_g',         'remapper', { in_min: 0, in_max: 1e4, out_min: 0, out_max: -1e4 }, 3, 2],
  ['g_ff',          'condition', { op: 0 }, 17, 3],                     // none yet ? −g (pull from behind) : g
  ['r_s',           'subtractor', {}, 7, 3],                            // r − D
  ['x',             'divider', {}, 8, 3],                               // r ÷ r_s
  ['x_c',           'remapper', { in_min: 1, in_max: 1000, out_min: 1, out_max: 1000 }, 9, 3],
  ['g_avg',         'multiplier', {}, 10, 3],

  // ---- standoff and distance ----
  ['so_ln',         'remapper', { in_min: 0, in_max: 1, out_min: LN(TUNE.standoff_min), out_max: LN(TUNE.standoff_max) }, 1, 4],
  ['so',            'exp', {}, 2, 4],
  ['standoff_m',    'datameter', { label: 'STANDOFF M', visible: true }, 3, 4],   // the standoff in metres, kept in view
  ['dist_r',        'data_router_2', {}, 1, 5],
  ['valid',         'remapper', { in_min: 1e18, in_max: 1e19, out_min: 1, out_max: 0 }, 2, 5],
  ['valid_r',       'data_router_2', {}, 3, 6],
  ['d1',            'subtractor', {}, 3, 5],                            // d − standoff
  ['d_sel',         'condition', { op: 1 }, 4, 5],                      // sees the target ? d − standoff : 0
  ['lead',          'remapper', { in_min: -1e5, in_max: 1e5, out_min: -1e5 * TUNE.lead_s, out_max: 1e5 * TUNE.lead_s }, 3, 7],
  ['d_plan',        'subtractor', {}, 5, 5],                            // − v · lead
  ['dplan_r',       'data_router_4', {}, 6, 5],

  // ---- the stopping profile ----
  ['a_net_raw',     'subtractor', {}, 11, 3],                           // a_brk − g_avg
  ['a_net',         'remapper', { in_min: TUNE.a_min, in_max: 1e4, out_min: TUNE.a_min, out_max: 1e4 }, 12, 3],
  ['a_net_c',       'min', {}, 13, 3],                                  // at most plan_frac · MAX ACCEL
  ['d_pos',         'remapper', { in_min: 0, in_max: 1e12, out_min: 0, out_max: 2e12 }, 7, 4],   // 2 · max(d_plan, 0)
  ['prof2',         'multiplier', {}, 13, 4],
  ['v_root',        'sqrt', {}, 14, 4],
  ['v_lin',         'remapper', { in_min: -1e9, in_max: 1e9, out_min: -1e9 * TUNE.k_hold, out_max: 1e9 * TUNE.k_hold }, 7, 6],
  ['v_prof',        'min', {}, 15, 5],

  // ---- thrust ----
  ['err',           'subtractor', {}, 16, 5],                           // v_prof − v
  ['a_des',         'remapper', { in_min: -1e4, in_max: 1e4, out_min: -1e4 * TUNE.k_speed, out_max: 1e4 * TUNE.k_speed }, 17, 5],
  ['a_hi',          'min', {}, 17, 4],                                  // a_des within ± MAX ACCEL
  ['a_lim',         'max', {}, 17, 6],
  ['t_in',          'subtractor', {}, 18, 5],                           // − g
  ['t_r',           'data_router_4', {}, 19, 5],
  ['divisor',       'condition', { op: 5 }, 19, 4],                     // t ≥ 0 ? a_meas : a_brk
  ['thr',           'divider', {}, 20, 5],
  ['thr_c',         'remapper', { in_min: -1, in_max: 1, out_min: -1, out_max: 1 }, 21, 5],

  // ---- SRBs ----
  ['ign_gate',      'min', {}, 18, 7],                                  // measured and the target in sight
  ['ign_ok',        'condition', { op: 3 }, 19, 7],                     // t > a_fwd + a_srb ? that : 0
  ['ignited',       'max', {}, 20, 7],                                  // a latch: its own output fed back
  ['ign_r',         'data_router_4', {}, 21, 7],
  ['tx_ignite',     'wireless_transmitter', { channel: 35, label: 'SOLID IGNITE' }, 22, 7],
  ['burn_t',        'accumulator', { mode: 0 }, 22, 8],                 // ticks since ignition
  ['burnout',       'remapper', { in_min: TUNE.srb_ticks - 1, in_max: TUNE.srb_ticks, out_min: 0, out_max: 1 }, 23, 8],
  ['brake_now',     'condition', { op: 2 }, 20, 9],                     // t < 0 ? 1 : 0
  ['ej_any',        'sum', {}, 24, 8],                                  // braking due, burnout, or Autopilot off
  ['ej_cond',       'multiplier', {}, 25, 8],                           // only once they are lit
  ['ejected',       'accumulator', { mode: 0 }, 26, 8],                 // never reset: they leave once
  ['ej_flag',       'remapper', { in_min: 0, in_max: 1, out_min: 0, out_max: 1 }, 27, 8],
  ['tx_eject',      'wireless_transmitter', { channel: 36, label: 'SOLID EJECT' }, 28, 8],
];

const E = `
autopilot.out auto_r.in
auto_r.a off.a
auto_r.b timer.in
auto_r.c thrust.a
off.out off_r.in
off_r.a timer.reset
off_r.b ej_any.c
off_r.c ahead_n.reset
timer.out timer_r.in
timer_r.a meas_done.in
timer_r.b coast.in
timer_r.c burn_level.in
timer_r.d fly_on.in
coast.out m_full.set
burn_level.out phase.false
meas_done.out m_diff.set
fly_on.out fly_r.in
fly_r.a phase.a
fly_r.b ign_gate.a
phase.out thrust.true
thrust.out tx_thrust.tx

rx_vz.rx vz_r.in
vz_r.a lead.in
vz_r.b err.b
vz_r.c gv.b
vz_r.d vz_r2.in
vz_r2.a dvz.in
vz_r2.b fast.in
fast.out ahead.true
dvz.out dvz_r.in
dvz_r.a m_full.value
dvz_r.b m_sub.b
m_full.out m_sub.a
m_sub.out m_diff.value
m_diff.out a_meas.in
a_meas.out am_r.in
am_r.a a_brk.a
am_r.b divisor.true
am_r.c srb_k.in
srb_k.out ign_ok.b
thrust_ratio.out a_brk.b
a_brk.out a_brk_r.in
a_brk_r.a a_net_raw.a
a_brk_r.b divisor.false
divisor.out thr.b
max_accel.out max_r.in
max_r.a a_hi.b
max_r.b neg_max.b
max_r.c plan_cap.in
neg_max.out a_lim.b
plan_cap.out a_net_c.b

gravitymeter.gravity grav_r.in
grav_r.a gv.a
grav_r.b g_r2.in
g_r2.a neg_g.in
g_r2.b g_ff.false
neg_g.out g_ff.true
ahead_n.out g_ff.a
g_ff.out t_in.b
grav_r.c dg.in
grav_r.d g_avg.a
gv.out r_est.a
dg.out r_est.b
r_est.out r_r.in
r_r.a r_s.a
r_r.b x.a
r_r.c ahead.a
ahead.out ahead_n.in
dplan_r.c r_s.b
r_s.out x.b
x.out x_c.in
x_c.out g_avg.b
g_avg.out a_net_raw.b
a_net_raw.out a_net.in
a_net.out a_net_c.a
a_net_c.out prof2.a

standoff.out so_ln.in
so_ln.out so.in
rx_dist.rx dist_r.in
dist_r.a valid.in
dist_r.b d1.a
so.out standoff_m.in
standoff_m.out d1.b
valid.out valid_r.in
valid_r.a d_sel.a
valid_r.b ign_gate.b
d1.out d_sel.true
d_sel.out d_plan.a
lead.out d_plan.b
d_plan.out dplan_r.in
dplan_r.a d_pos.in
dplan_r.b v_lin.in
d_pos.out prof2.b
prof2.out v_root.in
v_root.out v_prof.a
v_lin.out v_prof.b
v_prof.out err.a

err.out a_des.in
a_des.out a_hi.a
a_hi.out a_lim.a
a_lim.out t_in.a
t_in.out t_r.in
t_r.a thr.a
t_r.b ign_ok.a
t_r.c brake_now.a
t_r.d divisor.a
thr.out thr_c.in
thr_c.out phase.true

ign_gate.out ign_ok.true
ign_ok.out ignited.a
ignited.out ign_r.in
ign_r.a tx_ignite.tx
ign_r.b burn_t.in
ign_r.c ej_cond.b
ign_r.d ignited.b
burn_t.out burnout.in
brake_now.out ej_any.a
burnout.out ej_any.b
ej_any.out ej_cond.a
ej_cond.out ejected.in
ejected.out ej_flag.in
ej_flag.out tx_eject.tx
`.trim().split('\n').filter((l) => l.trim()).map((l) => {
  const [f, t] = l.trim().split(/\s+/);
  const [from_instance, from_port] = f.split('.');
  const [to_instance, to_port] = t.split('.');
  return { from_instance, from_port, to_instance, to_port };
});

const ids = new Set(N.map((n) => n[0]));
const usedOut = new Set(), usedIn = new Set();
for (const e of E) {
  for (const id of [e.from_instance, e.to_instance]) if (!ids.has(id)) throw new Error('unknown block ' + id);
  const k = e.from_instance + '.' + e.from_port, j = e.to_instance + '.' + e.to_port;
  if (usedOut.has(k)) throw new Error('output drives two inputs: ' + k);
  if (usedIn.has(j)) throw new Error('input has two drivers: ' + j);
  usedOut.add(k); usedIn.add(j);
}

const fmt = (x) => x.toLocaleString('en-US', { maximumFractionDigits: 3 });
const notes = [
  'Travel computer: flies to the target the Space Scanner sees ahead and stops a set distance short of it, on trips of 250,000 km or more, keeping the acceleration under MAX ACCEL so the ship holds together. Small Solid Fuel Thrusters (SRBs) can boost the first stage, reverse thrust may be weaker than forward, and the target\'s gravity is allowed for.',
  '',
  'Use',
  '- Engage it in space or hovering (not landed): point the nose at the target (by hand or with the target lock), set the STANDOFF lever, then switch Autopilot on.',
  '- STANDOFF: log scale, 10 m (down) to 10,000 km (up); 0.5 is about 10 km. The STANDOFF M Datameter shows it in metres.',
  '- MAX ACCEL (a Constant): the acceleration it keeps to, m/s^2, gravity included. ' + TUNE.max_accel + ' peaks at about 10, just under where the game starts straining joints (10.4); peaks run about 25% over the setting. Raise it if the ship holds together at more.',
  '- THRUST RATIO (a Constant): forward / reverse thrust of the main engines, SRBs left out: ' + fmt(TUNE.thrust_ratio) + ' = 8,279,000 / 4,374,000. Too high is safe (it brakes early and arrives later); too low can crash.',
  '- Both Constants sit on top of the circuit, showing their values (' + TUNE.max_accel + ' and ' + (+TUNE.thrust_ratio.toFixed(4)) + '); click one to change it.',
  '- The first ' + Math.round(TUNE.meas_ticks / 60) + ' s measure the ship at ' + (TUNE.meas_q * 100) + '% thrust, then coasting. Then it flies: it lights the SRBs only if mains and SRBs at full fit under MAX ACCEL, ejects them when it must start braking (or at burnout), brakes, and holds station at the standoff.',
  '- Autopilot off cuts thrust, and ejects the SRBs if they are lit (their thrust cannot be stopped otherwise).',
  '- The reverse thrusters must be able to hold the ship against the target\'s gravity at the standoff.',
  '',
  'Wiring (SHIP RADIOS)',
  '- In: FWD DIST (30) from a Space Scanner on the nose; Z SPEED (23) from a Velocity Meter, Directional, facing forward. Local: Gravitymeter, the Autopilot switch, the STANDOFF lever.',
  '- Out: THRUST CTL (1), -1..1: forward thrusters read it as it is, reverse thrusters with Reversed Input on. SOLID IGNITE (35): 1 lights the SRBs (switch their ignition power with it). SOLID EJECT (36): 1 ejects them (Decouplers).',
  '- A Large Fuel Thruster (30 s to respond) needs a longer measurement: raise the coast, burn_level, meas_done and fly_on Remappers\' thresholds.',
  '',
  'Built and checked against a 1-D flight model by tools/build_travel_computer.js and tools/travel_harness.js.',
].join('\n');

const diagram = {
  notes, name: 'travel computer',
  instances: N.map(([id, type_id, parameters, c, r]) => ({ id, type_id, parameters, position: { x: 40 + c * 240, y: 40 + r * 165 } })),
  edges: E,
};

if (require.main === module) {
  fs.writeFileSync(path.join(__dirname, '..', 'circuits', 'travel_computer.json'), JSON.stringify(diagram, null, 1));
  const outside = ['wireless_transmitter', 'gravitymeter', 'switch', 'slider'];
  const radio = diagram.instances.filter((i) => i.type_id === 'wireless_transmitter').length;
  console.log(`travel_computer.json: ${diagram.instances.length} parts (${diagram.instances.filter((i) => !outside.includes(i.type_id)).length} logic, ${radio} radio), ${E.length} wires`);
}

module.exports = { diagram, TUNE };
