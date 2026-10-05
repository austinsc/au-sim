'use strict';
// Generates circuits/quick_turn.json.  Run: node tools/build_quick_turn.js
// Fly it against a yaw model:          node tools/build_quick_turn.js --check
//
// Button-activated 180° turn. Press the button and the ship yaws round 180° as fast as its thrusters can stop it;
// while it turns, THRUST ENABLE (normally 1) is 0, so whatever it gates (the engines' throttle, say) is off.
//
//   inputs   turn_button   a Button (1 while pressed)
//            yaw_rate      an Axis Rotometer measuring yaw, deg/s (either sign: see below)
//   outputs  yaw           −1..1: + turns, − brakes (a Sign Splitter makes YAW+ / YAW− for one-way thrusters)
//            thrust_enable 1, or 0 while the turn runs
//
//   active    = an Accumulator counting the ticks the button is down, reset by done: non-zero while a turn runs (a
//               Memory latch fed the button raced its own set signal, one block longer, and missed short presses)
//   turned    = Σ yaw_rate since the turn started (an Accumulator reset on active's rising edge): 60 × degrees
//   p         = d|turned| per tick = the turn's progress rate, deg/s
//   left      = 180° − |turned| / 60
//   measuring = active, measure_ticks (half a second) late (a Delay)
//   a         = p half a second into the turn, at full yaw: the ship's own measure of its yaw authority, deg/s
//               (a Memory set as measuring rises; plus a_min, which only keeps the Divider off 0)
//   rate_cmd  = min(√(2 · c_plan · a · max(left, 0)), tail_gain · left): the fastest rate it can still stop from;
//               the linear term takes over in the last degrees and turns negative past 180°, so an overshoot is
//               pulled back
//   yaw       = measuring ? sat((rate_cmd − p) ÷ (c_band · a)) : active    (a Condition on measuring ≠ 0, then a
//               Remapper clamping to ±1): full yaw for the first half second, while a is measured; 0 when idle
//   done      = |rate_cmd| under tail_gain · tol_deg (that is, within tol_deg of 180°, either side) and |p| under
//               still_rate (both two-sided: a ship swinging back through 180° after an overshoot is not done); the
//               turn ends settle_ticks later (a Delay), the controller holding 180° meanwhile, so the thrusters are
//               idle when it lets go (ending at once left the brake on: the rate it reads lags the ship by the
//               circuit's ticks and the thrusters' spool-down). done counts only once measuring is up.
//
// Why it measures the ship (from the game's code, SpaceshipPartsApplyForces): the yaw thrusters' torque turns the ship,
// but whenever thrusters with a gimbal fire (electric, lift, fuel and atmospheric thrusters have one; maneuvering and
// RCS thrusters do not), their "angular stabilization" also drags the spin toward alpha · u, numerically (rad/s from
// rad/s²). A hovering ship therefore yaws at a rate set by the yaw throttle, capped at its yaw acceleration's number
// (10 deg/s² turns at most 10 deg/s), and stops within a second of the thrust ending; a ship coasting in space
// accelerates at alpha until braked. The same yaw loop must not chatter in the first case and must still brake in
// time in the second, for any ship. Half a second of full yaw tells them apart and sizes both: a ≈ 0.27 alpha coasting
// (still accelerating; the half second includes the circuit's ticks and the spool-up) but 0.65–1 alpha hovering
// (already at the cap), so planning and loop gain scale with a. A fixed alpha_plan (version 1) could not do both: it
// overshot 20–75° on a coasting ship weaker than planned and rang near 180° on a strong hovering one.
//
// The turn needs no sign: the yaw command starts positive, |turned| grows whichever way that turns the ship, and the
// controller only reasons about |turned| and its rate, so the rotometer and thruster signs cannot make it run away.
// done counts only once measuring is up. Every block outputs 0 for its first ticks after Fly Mode starts, which reads
// as "at 180° and still", and the Delay replayed that half a second later, swallowing an early press. And when a turn
// had settled within tol_deg of 180°, done stayed 1 for the ~10 ticks the next turn's reset took to reach it, which
// the latch itself let through: version 1 ended that turn after 0.6 s.
// Holding the button through the end of a turn starts another one at once, from wherever the ship then is (done
// wavers for a tick or two as it settles, and each gap in the reset lets the held button back in). A press within
// about a second after a turn is ignored: the reset outlasts the latch by measuring's half second. Every output drives
// one wire (the game's rule); the six Data Routers copy the signals used twice or more, one tick each. A ship already
// turning at the press measures wrong for that turn.
const fs = require('fs');
const path = require('path');

const num = (k, d) => (process.env[k] === undefined ? d : Number(process.env[k]));
const TUNE = {
  measure_ticks: num('MEASURE_TICKS', 30),            // full yaw this long, then a = p
  // a is ~0.27 alpha coasting (the half second includes the circuit's ticks and the thrusters' spool-up) and 0.65–1
  // alpha hovering. Swept against the model: c_band 1.2 let a strong hovering ship's yaw ring without end, 1.4 was the
  // edge, 1.6 leaves margin; c_plan 1.0 (braking planned at ~0.27 alpha coasting) overshoots 1–5°, 1.3 twice that.
  c_plan: num('C_PLAN', 1.0),                         // plan to brake at c_plan · a deg/s²
  c_band: num('C_BAND', 1.6),                         // full yaw at c_band · a deg/s of rate error
  a_min: num('A_MIN', 0.5),                           // deg/s added to a: never 0 (the first turn starts from it)
  tail_gain: num('TAIL_GAIN', 2),                     // per s: the linear rate command's slope near 180°
  tol_deg: 0.15,                                      // done within this of 180°... (the rate it then commands, at
                                                      // most tail_gain × 0.15 = 0.3 deg/s, is about still_rate)
  still_rate: 0.25,                                   // ...and turning slower than this, deg/s
  settle_ticks: 30,                                   // then hold 180° this long before letting go
};

// One wire per output port, as the game allows: a signal needed in two or more places goes through a Data Router (one
// tick each). Positions: the simulator's Tidy layout.
const instances = [], edges = [];
const add = (id, type_id, parameters, x, y) => instances.push({ id, type_id, parameters, position: { x, y } });
const wire = (a, ap, b, bp) => edges.push({ from_instance: a, from_port: ap, to_instance: b, to_port: bp });

add('turn_button', 'button', { out: 0 }, 60, 506);
add('yaw_rate', 'axis_rotometer', { angular_velocity: 0 }, 740, 332);
add('active', 'accumulator', { mode: 0 }, 400, 489);
add('active_split', 'data_router_4', {}, 740, 497);
add('thrust_enable', 'not', {}, 1080, 519);
add('turned', 'accumulator', { mode: 1 }, 1080, 317);          // reset on the turn's first tick
add('turned_abs', 'abs', {}, 1420, 343);
add('angle_split', 'data_router_4', {}, 1760, 316);
add('progress_rate', 'differentiator', { interval: 1, simulate: 0 }, 2100, 566);
add('rate_split', 'data_router_4', {}, 2440, 525);
add('measuring', 'delay', { ticks: TUNE.measure_ticks }, 1080, 800);     // active, half a second late
add('measuring_split', 'data_router_4', {}, 1420, 800);
add('measured', 'memory', { mode: 1 }, 2780, 800);             // p as measuring rises: half a second into the turn
add('ship_accel', 'remapper', { in_min: 0, in_max: 1000,       // c_band · (a + a_min): the rate error for full yaw
  out_min: TUNE.c_band * TUNE.a_min, out_max: TUNE.c_band * (1000 + TUNE.a_min) }, 3120, 800);
add('accel_split', 'data_router_2', {}, 3460, 800);
add('braking_room', 'remapper', { in_min: 0, in_max: 180 * 60, out_min: 360 * TUNE.c_plan / TUNE.c_band, out_max: 0 }, 2100, 50);
add('braking_scaled', 'multiplier', {}, 3800, 50);
add('rate_sqrt', 'sqrt', {}, 4140, 50);
add('rate_lin', 'remapper', { in_min: 0, in_max: 360 * 60, out_min: TUNE.tail_gain * 180, out_max: -TUNE.tail_gain * 180 }, 2100, 308);
add('rate_cmd', 'min', {}, 4480, 241);
add('cmd_split', 'data_router_2', {}, 4820, 278);
add('rate_err', 'subtractor', {}, 5160, 265);
add('rate_norm', 'divider', {}, 5500, 265);
add('steer', 'condition', { op: 1 }, 5840, 403);               // measuring ≠ 0 ? rate_norm : active (0, or ≥ 1)
add('yaw', 'remapper', { in_min: -1, in_max: 1, out_min: -1, out_max: 1 }, 6180, 216);   // clamp to ±1
add('cmd_abs', 'abs', {}, 5160, 439);
add('near', 'remapper', { in_min: TUNE.tail_gain * TUNE.tol_deg, in_max: 2 * TUNE.tail_gain * TUNE.tol_deg, out_min: 1, out_max: 0 }, 5500, 474);
add('rate_abs', 'abs', {}, 2780, 559);
add('still', 'remapper', { in_min: TUNE.still_rate, in_max: 2 * TUNE.still_rate, out_min: 1, out_max: 0 }, 3120, 536);
add('done', 'min', {}, 5840, 649);
add('done_turning', 'min', {}, 6180, 695);                    // done counts only once measuring is up
add('settled', 'delay', { ticks: TUNE.settle_ticks }, 6520, 684);

wire('turn_button', 'out', 'active', 'in');
wire('settled', 'out', 'active', 'reset');
wire('active', 'out', 'active_split', 'in');
wire('active_split', 'a', 'thrust_enable', 'in');
wire('active_split', 'b', 'steer', 'false');                 // full yaw while measuring, 0 when idle
wire('active_split', 'c', 'turned', 'reset');
wire('yaw_rate', 'angular_velocity', 'turned', 'in');
wire('turned', 'out', 'turned_abs', 'in');
wire('turned_abs', 'out', 'angle_split', 'in');
wire('angle_split', 'a', 'progress_rate', 'in');
wire('angle_split', 'b', 'braking_room', 'in');
wire('angle_split', 'c', 'rate_lin', 'in');
wire('active_split', 'd', 'measuring', 'in');
wire('measuring', 'out', 'measuring_split', 'in');
wire('measuring_split', 'a', 'measured', 'set');
wire('measuring_split', 'b', 'steer', 'a');                  // steer.b unwired = 0
wire('measuring_split', 'c', 'done_turning', 'b');
wire('rate_split', 'c', 'measured', 'value');
wire('measured', 'out', 'ship_accel', 'in');
wire('ship_accel', 'out', 'accel_split', 'in');
wire('accel_split', 'a', 'braking_scaled', 'b');
wire('accel_split', 'b', 'rate_norm', 'b');
wire('braking_room', 'out', 'braking_scaled', 'a');
wire('braking_scaled', 'out', 'rate_sqrt', 'in');
wire('rate_sqrt', 'out', 'rate_cmd', 'a');
wire('rate_lin', 'out', 'rate_cmd', 'b');
wire('rate_cmd', 'out', 'cmd_split', 'in');
wire('cmd_split', 'a', 'rate_err', 'a');
wire('cmd_split', 'b', 'cmd_abs', 'in');
wire('progress_rate', 'out', 'rate_split', 'in');
wire('rate_split', 'a', 'rate_err', 'b');
wire('rate_split', 'b', 'rate_abs', 'in');
wire('rate_err', 'out', 'rate_norm', 'a');
wire('rate_norm', 'out', 'steer', 'true');
wire('steer', 'out', 'yaw', 'in');
wire('cmd_abs', 'out', 'near', 'in');
wire('rate_abs', 'out', 'still', 'in');
wire('near', 'out', 'done', 'a');
wire('still', 'out', 'done', 'b');
wire('done', 'out', 'done_turning', 'a');
wire('done_turning', 'out', 'settled', 'in');

// the circuit's own notes (the simulator's notes panel: plain text, first key; one line per paragraph or bullet, as
// the panel wraps lines itself)
const notes = [
  'Quick turn: press the button and the ship yaws round 180° as fast as it can still stop. THRUST ENABLE is 1, and 0 while the turn runs.',
  '',
  'Inputs',
  '- turn_button: a Button. Press and release. Holding it past the end of a turn starts another at once, from wherever the ship is.',
  '- yaw_rate: an Axis Rotometer measuring yaw (deg/s). Either sign works, and so does either thruster direction: the ship turns whichever way positive yaw pushes it.',
  '',
  'Outputs',
  '- yaw: -1..1, + turns, - brakes. Feed a two-way thruster, or a Sign Splitter into YAW+ / YAW- (channels 12 / 13).',
  '- thrust_enable: multiply your throttle by it, or feed both into a Minimum.',
  '',
  'How it fits any ship',
  '- Each turn starts with half a second of full yaw; the yaw rate it reaches (measured) sets how hard the turn plans to brake and how gently it steers. No tuning.',
  '- Hovering, the lift thrusters\' angular stabilization caps the yaw rate at the yaw acceleration\'s number (10 deg/s² turns at most 10 deg/s), so a hovering turn is slower than one in space.',
  '- Start a turn with the ship still: a ship already turning measures wrong. Wait about a second between turns.',
  '',
  'Thrusters',
  '- Maneuvering thrusters push as well as turn (the game applies their full force to the ship). Mount each direction as a couple, one at the bow pushing one way and one at the stern pushing the other, and the pushes cancel; far from the centre of mass gives the most turn.',
  '',
  'Built and checked against a yaw model by tools/build_quick_turn.js (--check).',
].join('\n');

const diagram = { notes, name: 'quick turn', instances, edges };

// ---- the check: a yaw model flown by the circuit ----
// Follows the game's force code (SpaceshipPartsApplyForces). The yaw output goes through a Sign Splitter (one tick) to
// the YAW+ and YAW− thruster sets; each set's throttle slews toward its input at 1 / accel_time per second (the
// maneuvering thrusters take 0.1–0.35 s). Each tick omega += rcsSign · alpha · u / 60 (u = YAW+ − YAW−, deg/s, alpha
// in deg/s²); then, if gimballed thrusters fire (`pull` > 0, their angular stabilization in deg/s²), omega moves toward
// rcsSign · alpha · u by at most pull / 60. The rotometer reads rotSign · omega. The button is held for `press` ticks
// from tick `at` (30: half a second after Fly Mode starts); `turns` presses come 25 s apart, the result is the last.
function turn(d, opts = {}) {
  const { CircuitEngine } = require('../engine.js');
  const o = { alpha: 16, pull: 0, rcsSign: 1, rotSign: 1, accelTime: 0.25, press: 1, at: 30, omega0: 0, turns: 1, lag: 1, ...opts };
  const e = new CircuitEngine(d);
  const inst = (id) => e.instances.get(id);
  let omega = o.omega0, psi = 0, up = 0, un = 0, r = null;
  const wires = new Array(o.lag).fill(0);                                    // the Sign Splitter's tick (and any more)
  for (let n = 0, at = o.at, tick = 0; n < o.turns; n++, at += 25 * 60) {
    let start = null, end = null, maxPsi = 0, yawEarly = 0, flips = 0, lastSign = 0;
    for (; tick < at + 60 * 120; tick++) {
      inst('yaw_rate').params.angular_velocity = o.rotSign * omega;
      inst('turn_button').params.out = tick >= at && tick < at + o.press ? 1 : 0;
      e.step();
      const snap = e.snapshot();
      const cmd = snap.yaw.out, en = snap.thrust_enable.out;
      if (tick === at) psi = 0;                                               // measure the turn from the press
      if (start === null && en < 0.5) start = tick;
      if (start !== null && end === null && en > 0.5) end = tick;
      if (start === null && Math.abs(cmd) > 1e-9) yawEarly++;                 // yaw before the turn starts
      if (start !== null && end === null) {                                   // yaw reversals while turning
        const s = Math.sign(Math.round(cmd * 100));
        if (s && lastSign && s !== lastSign) flips++;
        if (s) lastSign = s;
      }
      const slew = 1 / o.accelTime / 60;
      const split = wires.shift();
      wires.push(cmd);
      up += Math.max(-slew, Math.min(slew, Math.min(1, Math.max(0, split)) - up));
      un += Math.max(-slew, Math.min(slew, Math.min(1, Math.max(0, -split)) - un));
      omega += o.rcsSign * o.alpha * (up - un) / 60;
      if (o.pull > 0) {
        const target = o.rcsSign * o.alpha * (up - un), step = o.pull / 60;
        omega = Math.abs(target - omega) <= step ? target : omega + Math.sign(target - omega) * step;
      }
      psi += omega / 60;
      maxPsi = Math.max(maxPsi, Math.abs(psi));
      if (end !== null && tick > end + 120) break;                            // 2 s after the turn, to see any drift
    }
    r = {
      ok: end !== null && Math.abs(Math.abs(psi) - 180) < 2 && Math.abs(omega) < 0.5,
      turned: +Math.abs(psi).toFixed(1), overshoot: +(maxPsi - 180).toFixed(1), drift: +omega.toFixed(2),
      time: end === null ? null : +((end - start) / 60).toFixed(1), reversals: flips,
      enableOffFrom: start - at, yawBeforeTurn: yawEarly, measured: +(e.snapshot().measured?.out ?? NaN).toFixed(2),
    };
    if (!r.ok) break;
    tick = at + 25 * 60;
  }
  return r;
}

// the cases --check flies: coasting and hovering ships from weak to strong, thruster and rotometer signs, spool times
function cases() {
  const out = [];
  for (const alpha of [2, 4, 8, 16, 32, 64]) out.push({ alpha });
  for (const alpha of [3, 8, 24, 64]) for (const k of [0.5, 1, 3]) out.push({ alpha, pull: k * alpha });
  for (const [rcsSign, rotSign] of [[-1, 1], [1, -1], [-1, -1]]) out.push({ alpha: 16, rcsSign, rotSign }, { alpha: 16, pull: 16, rcsSign, rotSign });
  for (const accelTime of [0.1, 0.35]) out.push({ alpha: 8, accelTime }, { alpha: 64, accelTime }, { alpha: 32, pull: 32, accelTime });
  out.push({ alpha: 16, press: 90 });                                       // button held 1.5 s
  out.push({ alpha: 16, turns: 2 }, { alpha: 64, pull: 64, turns: 2 });      // repeat turns (one once ended itself)
  out.push({ alpha: 64, lag: 4 }, { alpha: 64, pull: 192, lag: 4 }, { alpha: 3, pull: 1.5, lag: 4 });   // 3 more ticks
  return out;
}

if (require.main === module) {
  fs.writeFileSync(path.join(__dirname, '..', 'circuits', 'quick_turn.json'), JSON.stringify(diagram, null, 1));
  const logic = instances.filter((i) => !['button', 'axis_rotometer'].includes(i.type_id)).length;
  console.log(`quick_turn.json: ${instances.length} blocks (${logic} logic), ${edges.length} wires; ` +
    `c_plan ${TUNE.c_plan}, c_band ${TUNE.c_band}, tail_gain ${TUNE.tail_gain}, measure ${TUNE.measure_ticks} ticks`);
  if (process.argv.includes('--check')) {
    let bad = 0;
    for (const c of cases()) {
      const r = turn(diagram, c);
      if (!r.ok) bad++;
      console.log(`${Object.entries(c).map(([k, v]) => `${k} ${v}`).join(', ').padEnd(44)} ${r.ok ? 'ok  ' : 'FAIL'} ` +
        `time ${String(r.time).padStart(5)} s, overshoot ${String(r.overshoot).padStart(5)}°, a ${r.measured}, reversals ${r.reversals}`);
    }
    console.log(bad ? `${bad} FAILED` : 'all ok');
  }
}

module.exports = { diagram, turn, cases, TUNE };
