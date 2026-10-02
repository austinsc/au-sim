'use strict';
// Generates circuits/raster_sweep_v3.json.  Run: node tools/build_raster_sweep_v3.js
// Test it against the attitude model:         node tools/attitude_harness.js circuits/raster_sweep_v3.json
//
// Compact closed-loop target lock (38 blocks). Search by hand with the Auto switch off, then switch it on.
// The circuit keeps the scanner's cone just wide enough to see the target and steers the nose so that the cone
// keeps shrinking. It stops once the 1° cone sees the target.
//
//   cone      W = cone lever × e^L, and the scanner's cone input is 1.02 − W, so W ≈ cone width / 49 (W = 0 is
//             1°, W = 1 is 50°). In manual L = 0, so the lever sets the cone (up = wider). In Auto, L steps
//             down 1.5% a tick while the target is seen and up while it is not, so the cone hugs the target at
//             the same relative sharpness from 50° down to 1°.
//   target    switching Auto on stores the scanner distance D0. A reading up to 5% beyond D0 is the target, and
//             so is a nearer one (the scanner reports only the nearest body in the cone). A farther reading, or
//             the empty cone (1e20), means the target is not in the cone.
//   steer     the nose moves straight along a heading at gain × W deg/s (about 0.27 × its angle from the
//             target). Once a second it checks whether the cone widened since the last check; if so it has passed
//             the target along this line, and the heading turns 90° (coordinate descent). At 1° with the target
//             seen, L keeps falling, so W and the speed decay to zero and the ship stops.
//   rate loop in Auto, RCS = joystick − D × (rotometer rate − steer): the damping stops rotation fast and makes the
//             nose follow the steer rate. In manual, RCS = joystick, exactly as without the circuit.
//
// Tuning: tune_damp = −D with D ≈ 5 / (deg/s² at full stick): hold full yaw for 1 s in manual and read the yaw
// rotometer. Too small and the ship drifts through its moves; too large and it buzzes.
// Hardware: Space Scanner facing the nose (cone input from cone_cmd); RCS Controller yaw/pitch from rcs_yaw /
// rcs_pitch; Joystick 3D yaw/pitch into this circuit; a lever for the cone width; a Switch for Auto; two Axis
// Rotometers, one upright (yaw rate) and one on its side (pitch rate), each mounted so it reads positive for
// stick right / stick up.
const fs = require('fs');
const path = require('path');

const EQ = 0, NE = 1, LT = 2, GT = 3, LE = 4, GE = 5;
const DEFAULTS = {
  probe: 60,          // ticks between "has the cone widened?" checks (a Differentiator interval: 1..60)
  narrow: -0.015,     // L step per tick while the target is seen (the cone shrinks 1.5%) ...
  widen: 0.015,       // ... and while it is not
  turn: Math.PI / 2,  // heading turn after a check that saw the cone widen (radians)
  match: 1.05,        // the target: no more than 5% farther than D0
  damp: 0.25,         // D: RCS command per deg/s of rate error (≈ 5 / deg/s² at full stick)
  gain: 6.6,          // approach speed: gain × W deg/s
};

function build(settings = {}) {
  const S = { ...DEFAULTS, ...settings };
  const B = [];                     // [id, type_id, params]
  const W = [];                     // ['id.port', 'id.port'] (one source may feed many inputs)
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
  const out = (id) => `${id}.out`;

  // ---- inputs ----
  block('in_scan_dist', 'slider', { value: 1e20 });   // Space Scanner distance (1e20 = nothing in the cone)
  block('in_yaw_rate', 'slider', { value: 0 });       // Axis Rotometer, yaw (deg/s)
  block('in_pitch_rate', 'slider', { value: 0 });     // Axis Rotometer, pitch (deg/s)
  block('in_joy_yaw', 'slider', { value: 0 });        // Joystick 3D yaw, -1..1
  block('in_joy_pitch', 'slider', { value: 0 });      // Joystick 3D pitch, -1..1
  block('in_cone_manual', 'slider', { value: 0.5 });  // cone lever: 0 = 1°, 1 = 50° (manual cone, and Auto's start)
  block('in_auto', 'toggle', { value: 0 });           // Auto switch

  // ---- tuning ----
  block('tune_damp', 'constant', { value: -S.damp });       // −D ≈ −5 / (deg/s² at full stick)
  block('tune_gain', 'constant', { value: -S.gain });       // approach speed, deg/s per unit of W (sign: see steer)
  block('tune_match', 'constant', { value: S.match });      // the target: ≤ 5% farther than D0
  block('tune_narrow', 'constant', { value: S.narrow });    // cone tracking: L step while seen ...
  block('tune_widen', 'constant', { value: S.widen });      // ... and while not seen
  block('tune_turn', 'constant', { value: S.turn });        // heading turn after the cone widened (radians)

  // ---- mode: Auto stores the target distance and frees the cone tracker ----
  one('manual', 'not', out('in_auto'));
  two('d0_scale', 'multiplier', out('in_scan_dist'), out('tune_match'));
  block('d0', 'memory', { mode: 1 });                 // pulse mode: stores once, when Auto switches on
  wire(out('d0_scale'), 'd0.value');
  wire(out('in_auto'), 'd0.set');

  // ---- cone tracker: the target (or something nearer) in the cone → narrow, else widen ----
  cond('L_step', LE, out('in_scan_dist'), out('d0'), out('tune_narrow'), out('tune_widen'));
  block('L', 'accumulator', { mode: 0 });                                    // held at 0 in manual
  wire(out('L_step'), 'L.in');
  wire(out('manual'), 'L.reset');
  one('W_rel', 'exp', out('L'));
  two('W', 'multiplier', out('W_rel'), out('in_cone_manual'));               // ≈ cone width / 49
  // cone input = 1.02 − W, clamped to 0..1.02 (→ Space Scanner, which clamps it to 0..1)
  block('cone_cmd', 'remapper', { in_min: 0, in_max: 1.02, out_min: 1.02, out_max: 0 });
  wire(out('W'), 'cone_cmd.in');

  // ---- heading: once per check, turn 90° if the cone widened since the last check ----
  block('widened', 'differentiator', { interval: S.probe });                 // W now − W one check ago
  wire(out('W'), 'widened.in');
  // `widened` changes only when it samples, so a 1-tick Differentiator of it is non-zero for exactly that tick,
  // in step with this check's decision (both are one block from `widened`)
  block('checked', 'differentiator', { interval: 1 });
  wire(out('widened'), 'checked.in');
  cond('turn_amt', GT, out('widened'), null, out('tune_turn'), null);
  cond('turn', NE, out('checked'), null, out('turn_amt'), null);
  block('heading', 'accumulator', { mode: 0 });
  wire(out('turn'), 'heading.in');
  one('head_x', 'cos', out('heading'));
  one('head_y', 'sin', out('heading'));

  // ---- steer and rate loops: in Auto, RCS = joystick − D × rate + D × gain × min(W, 1) × heading ----
  two('damp_k', 'multiplier', out('in_auto'), out('tune_damp'));           // −D in Auto, 0 in manual
  two('speed_lim', 'min', out('W'), out('in_auto'));                        // W, at most 1 (0 in manual)
  two('speed_d', 'multiplier', out('speed_lim'), out('damp_k'));            // −D × W
  two('speed', 'multiplier', out('speed_d'), out('tune_gain'));             // D × gain × W: the damping turns it
  two('steer_yaw', 'multiplier', out('speed'), out('head_x'));              //   into gain × W deg/s, whatever D is
  two('steer_pitch', 'multiplier', out('speed'), out('head_y'));
  two('damp_yaw', 'multiplier', out('in_yaw_rate'), out('damp_k'));
  two('damp_pitch', 'multiplier', out('in_pitch_rate'), out('damp_k'));
  block('rcs_yaw', 'sum');
  wire(out('in_joy_yaw'), 'rcs_yaw.a'); wire(out('steer_yaw'), 'rcs_yaw.b'); wire(out('damp_yaw'), 'rcs_yaw.c');
  block('rcs_pitch', 'sum');
  wire(out('in_joy_pitch'), 'rcs_pitch.a'); wire(out('steer_pitch'), 'rcs_pitch.b'); wire(out('damp_pitch'), 'rcs_pitch.c');

  // ---- resolve fan-out: the game lets an output feed one input, so add Data Routers ----
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
  for (const [src, targets] of bySrc) {
    if (targets.length === 1) { edge(src, targets[0]); continue; }
    if (targets.length > 4) throw new Error(`${src} feeds ${targets.length} inputs`);
    const r = block(`${src.split('.')[0]}_fan`, targets.length === 2 ? 'data_router_2' : 'data_router_4');
    edge(src, `${r}.in`);
    targets.forEach((t, i) => edge(`${r}.${PORTS4[i]}`, t));
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
  return {
    instances: B.map(([id, type_id, parameters]) => {
      const c = depth.get(id), r = rows.get(c) || 0;
      rows.set(c, r + 1);
      return { id, type_id, parameters, position: { x: 40 + c * 240, y: 40 + r * 150 }, color: '#7aa2f7', mirrored: false };
    }),
    edges, groups: [], max_per_column: 4, max_rows: 4, max_columns: 8,
  };
}

const logicBlocks = (d) => d.instances.filter((b) => !['slider', 'toggle'].includes(b.type_id)).length;
module.exports = { build, DEFAULTS, logicBlocks };

if (require.main === module) {
  const diagram = build();
  fs.writeFileSync(path.join(__dirname, '..', 'circuits', 'raster_sweep_v3.json'), JSON.stringify(diagram, null, 2) + '\n');
  const n = (f) => diagram.instances.filter((b) => f(b.type_id)).length;
  console.log(`raster_sweep_v3.json: ${logicBlocks(diagram)} blocks (${n((t) => t === 'constant')} constants, ` +
    `${n((t) => t.startsWith('data_router'))} routers) + ${n((t) => ['slider', 'toggle'].includes(t))} inputs, ` +
    `${diagram.edges.length} wires`);
}
