'use strict';
// Run with:  node --test
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { CircuitEngine, TYPES } = require('../engine.js');

const loadCircuit = (name) => require(path.join(__dirname, '..', 'circuits', name));

// ---- helpers --------------------------------------------------------------
// nodes: { id: [type_id, params] }, wires: ['from.port to.port', ...]
function build(nodes, wires = []) {
  return new CircuitEngine({
    instances: Object.entries(nodes).map(([id, [type_id, parameters = {}]]) => ({ id, type_id, parameters })),
    edges: wires.map((w) => {
      const [from, to] = w.split(/\s+/);
      const [from_instance, from_port] = from.split('.');
      const [to_instance, to_port] = to.split('.');
      return { from_instance, from_port, to_instance, to_port };
    }),
  });
}

// Evaluate one block with constant inputs; returns its outputs once settled
// (constant → block is two ticks).
function evalBlock(type_id, inputs = {}, params = {}) {
  const nodes = { dut: [type_id, params] };
  const wires = [];
  for (const [port, value] of Object.entries(inputs)) {
    nodes['c_' + port] = ['constant', { value }];
    wires.push(`c_${port}.out dut.${port}`);
  }
  const e = build(nodes, wires);
  e.step(2);
  return e.snapshot().dut;
}

// Feed a block one input sample per tick; returns its output after consuming
// each sample. out[i] is the block's output on the tick it processed in[i].
function runStateful(type_id, params, seq) {
  const ports = Object.keys(seq);
  const nodes = { dut: [type_id, params] };
  const wires = [];
  for (const p of ports) {
    nodes['src_' + p] = ['slider', { value: 0 }];
    wires.push(`src_${p}.out dut.${p}`);
  }
  const e = build(nodes, wires);
  const n = seq[ports[0]].length;
  const outs = [];
  for (let t = 0; t <= n; t++) {
    for (const p of ports) e.instances.get('src_' + p).params.value = seq[p][Math.min(t, n - 1)];
    e.step();
    if (t > 0) outs.push(e.snapshot().dut.out);
  }
  return outs;
}

// ---- topology -------------------------------------------------------------
test('topology: unknown type_id is rejected', () => {
  assert.throws(() => build({ x: ['divide'] }), /Unknown block type_id "divide"/);
  assert.throws(() => build({ x: ['nor'] }), /Unknown block type_id "nor"/, 'the game has no NOR part');
});

test('topology: edges to/from unknown instances are rejected', () => {
  assert.throws(() => build({ a: ['constant'] }, ['a.out ghost.a']), /unknown instance "ghost"/);
  assert.throws(() => build({ a: ['adder'] }, ['ghost.out a.a']), /unknown instance "ghost"/);
});

test('topology: any feedback loop is legal, since every block takes a tick', () => {
  assert.doesNotThrow(() => build({ p: ['adder'], q: ['adder'] }, ['p.out q.a', 'q.out p.a']));
});

// ---- the game's timing rule ------------------------------------------------
test('timing: every component takes one tick (manual: 10 routers → 11 ticks)', () => {
  const nodes = { lever: ['slider', { value: 0 }], meter: ['datameter'] };
  const wires = [];
  let prev = 'lever.out';
  for (let i = 1; i <= 10; i++) {
    nodes['r' + i] = ['data_router_2'];
    wires.push(`${prev} r${i}.in`);
    prev = `r${i}.a`;
  }
  wires.push(`${prev} meter.in`);
  const e = build(nodes, wires);
  e.instances.get('lever').params.value = 1;
  let arrived = null;
  for (let t = 1; t <= 20 && arrived === null; t++) {
    e.step();
    if (e._readPort('meter', 'in') === 1) arrived = t;
  }
  assert.equal(arrived, 11);
});

test('timing: blocks evaluate from last tick, so declaration order never matters', () => {
  const mk = (order) => {
    const all = { c: ['constant', { value: 3 }], m: ['multiplier'], a: ['adder'] };
    return build(Object.fromEntries(order.map((k) => [k, all[k]])), ['c.out a.a', 'a.out m.a']);
  };
  const x = mk(['c', 'a', 'm']), y = mk(['m', 'a', 'c']);
  for (let t = 0; t < 4; t++) {
    x.step(); y.step();
    assert.deepEqual(x.snapshot().m, y.snapshot().m, `tick ${t + 1}`);
  }
});

test('timing: NOT + router self-loop oscillates (the community clock, minus NOR)', () => {
  const e = build({ n: ['not'], r: ['data_router_2'] }, ['n.out r.in', 'r.a n.in']);
  const seq = [];
  for (let t = 0; t < 8; t++) { e.step(); seq.push(e.snapshot().n.out); }
  assert.deepEqual(seq, [1, 1, 0, 0, 1, 1, 0, 0], 'period 4 ticks for a 2-block loop');
});

test('timing: NOR built from OR + NOT costs two ticks', () => {
  const e = build(
    { a: ['constant', { value: 0 }], b: ['constant', { value: 0 }], or: ['or'], not: ['not'] },
    ['a.out or.a', 'b.out or.b', 'or.out not.in'],
  );
  e.step(3);
  assert.equal(e.snapshot().not.out, 1);
});

// ---- combinational blocks -------------------------------------------------
test('sources', () => {
  assert.equal(evalBlock('constant', {}, { value: 7.5 }).out, 7.5);
  assert.equal(evalBlock('slider', {}, { value: -3 }).out, -3);
  assert.equal(evalBlock('toggle', {}, { value: 1 }).out, 1);
  assert.equal(evalBlock('toggle', {}, { value: 5 }).out, 1, 'toggle normalises truthy to 1');
  assert.equal(evalBlock('toggle', {}, { value: 0 }).out, 0);
});

test('unwired inputs read as 0, except where the game says otherwise', () => {
  assert.equal(evalBlock('adder', { a: 4 }).out, 4);
  assert.equal(evalBlock('subtractor', { b: 4 }).out, -4);
  assert.equal(evalBlock('condition', { a: 1, b: 1 }, { op: 0 }).out, 1, 'unwired True defaults to 1');
  assert.equal(evalBlock('condition', { a: 1, b: 2 }, { op: 0 }).out, 0, 'unwired False defaults to 0');
  assert.equal(evalBlock('fader', {}, { value: 0.25 }).out, 0.25, 'unwired Fader input defaults to 1');
});

test('arithmetic', () => {
  assert.equal(evalBlock('adder', { a: 2, b: 3 }).out, 5);
  assert.equal(evalBlock('subtractor', { a: 2, b: 3 }).out, -1);
  assert.equal(evalBlock('multiplier', { a: -2, b: 3 }).out, -6);
  assert.equal(evalBlock('divider', { a: 7, b: 2 }).out, 3.5);
  assert.equal(evalBlock('divider', { a: 7, b: 0 }).out, 0, 'divide by zero yields 0');
  assert.equal(evalBlock('mod', { a: 370, b: 360 }).out, 10);
  assert.equal(evalBlock('mod', { a: 5, b: 0 }).out, 0, 'mod by zero yields 0');
  assert.equal(evalBlock('mod', { a: -10, b: 360 }).out, -10, 'JS remainder keeps the sign of the dividend');
  assert.equal(evalBlock('power', { a: 3, b: 2 }).out, 9);
  assert.equal(evalBlock('max', { a: -1, b: 0.01 }).out, 0.01);
  assert.equal(evalBlock('min', { a: -1, b: 0.01 }).out, -1);
  assert.equal(evalBlock('abs', { in: -4.5 }).out, 4.5);
  assert.equal(evalBlock('sqrt', { in: 16 }).out, 4);
  assert.equal(evalBlock('sqrt', { in: -16 }).out, 0, 'sqrt clamps negatives to 0');
  assert.ok(Math.abs(evalBlock('exp', { in: 1 }).out - Math.E) < 1e-12);
  assert.ok(Math.abs(evalBlock('log', { in: Math.E }).out - 1) < 1e-12);
  assert.equal(evalBlock('log', { in: -1 }).out, 0, 'log of non-positive yields 0');
  assert.equal(evalBlock('sum', { a: 1, b: 2, c: 3, d: 4, e: 5, f: 6, g: 7 }).out, 28);
  assert.equal(evalBlock('sum', { a: 1, g: 7 }).out, 8);
  assert.equal(evalBlock('fader', { in: 8 }, { value: 0.5 }).out, 4);
  assert.equal(evalBlock('fader', { in: 8 }, { value: 3 }).out, 8, 'fader clamps to 0..1');
});

test('round modes (engine: 0 round, 1 floor, 2 ceil); halves round away from zero like the game', () => {
  assert.equal(evalBlock('round', { in: 2.5 }, { mode: 0 }).out, 3);
  assert.equal(evalBlock('round', { in: -2.5 }, { mode: 0 }).out, -3);
  assert.equal(evalBlock('round', { in: 2.7 }, { mode: 1 }).out, 2);
  assert.equal(evalBlock('round', { in: 2.1 }, { mode: 2 }).out, 3);
});

test('remapper', () => {
  const p = { in_min: 0, in_max: 10, out_min: -1, out_max: 1 };
  assert.equal(evalBlock('remapper', { in: 0 }, p).out, -1);
  assert.equal(evalBlock('remapper', { in: 5 }, p).out, 0);
  assert.equal(evalBlock('remapper', { in: 20 }, p).out, 1, 'clamps to the output range, as in the game');
  assert.equal(evalBlock('remapper', { in: -5 }, p).out, -1);
  assert.equal(evalBlock('remapper', { in: 5 }, { in_min: 10, in_max: 0, out_min: 0, out_max: 1 }).out, 0.5, 'reversed input range');
  assert.equal(evalBlock('remapper', { in: 5 }, { in_min: 1, in_max: 1, out_min: 4, out_max: 9 }).out, 9, 'empty input range: a step');
  assert.equal(evalBlock('remapper', { in: 0 }, { in_min: 1, in_max: 1, out_min: 4, out_max: 9 }).out, 4);
});

test('trig takes and returns radians', () => {
  const near = (a, b) => Math.abs(a - b) < 1e-12;
  assert.ok(near(evalBlock('sin', { in: Math.PI / 2 }).out, 1));
  assert.ok(near(evalBlock('cos', { in: Math.PI }).out, -1));
  assert.ok(near(evalBlock('tan', { in: Math.PI / 4 }).out, 1));
  assert.ok(Math.abs(evalBlock('sin', { in: 90 }).out - 1) > 0.1, 'degrees are not accepted');
  assert.ok(near(evalBlock('asin', { in: 1 }).out, Math.PI / 2));
  assert.ok(near(evalBlock('acos', { in: -1 }).out, Math.PI));
  assert.ok(near(evalBlock('asin', { in: 2 }).out, Math.PI / 2), 'asin clamps out-of-range input');
  assert.ok(near(evalBlock('atan', { in: 1 }).out, Math.PI / 4));
  assert.ok(near(evalBlock('atan2', { y: 1, x: -1 }).out, 3 * Math.PI / 4));
  assert.ok(near(evalBlock('sinh', { in: 0 }).out, 0));
  assert.ok(near(evalBlock('cosh', { in: 0 }).out, 1));
  assert.ok(near(evalBlock('tanh', { in: 0 }).out, 0));
});

test('logic gates', () => {
  const truth = { and: [0, 0, 0, 1], or: [0, 1, 1, 1], xor: [0, 1, 1, 0] };
  const pairs = [[0, 0], [0, 1], [1, 0], [1, 1]];
  for (const [gate, expected] of Object.entries(truth)) {
    pairs.forEach(([a, b], i) => assert.equal(evalBlock(gate, { a, b }).out, expected[i], `${gate}(${a},${b})`));
  }
  assert.equal(evalBlock('not', { in: 0 }).out, 1);
  assert.equal(evalBlock('not', { in: 3 }).out, 0);
  assert.equal(evalBlock('and', { a: 2, b: -1 }).out, 1, 'any non-zero is truthy');
});

test('logic_value and simple_threshold are inclusive', () => {
  assert.equal(evalBlock('logic_value', { in: 0.5 }).out, 1);
  assert.equal(evalBlock('logic_value', { in: 0.49 }).out, 0);
  assert.equal(evalBlock('simple_threshold', { in: 0.5 }, { threshold: 0.5 }).out, 1);
  assert.equal(evalBlock('simple_threshold', { in: 0.49 }, { threshold: 0.5 }).out, 0);
});

test('condition ops 0..5 (aupbuilder encoding)', () => {
  const cases = [ // [op, a, b, expectTrue]
    [0, 2, 2, true], [0, 2, 3, false],
    [1, 2, 3, true], [1, 2, 2, false],
    [2, 1, 2, true], [2, 2, 2, false],
    [3, 3, 2, true], [3, 2, 2, false],
    [4, 2, 2, true], [4, 3, 2, false],
    [5, 2, 2, true], [5, 1, 2, false],
  ];
  for (const [op, a, b, t] of cases) {
    assert.equal(evalBlock('condition', { a, b, true: 10, false: -10 }, { op }).out, t ? 10 : -10, `op ${op}: ${a} vs ${b}`);
  }
  assert.equal(evalBlock('condition', { a: 1, b: 1, true: 10, false: -10 }, { op: 9 }).out, -10, 'unknown op picks False');
});

test("condition Equal / Not Equal use the game's tolerance (relative 1e-6, absolute 2^-20)", () => {
  const eq = (a, b) => evalBlock('condition', { a, b, true: 10, false: -10 }, { op: 0 }).out === 10;
  assert.ok(eq(1000, 1000 + 1e-4), 'within 1e-6 relative');
  assert.ok(!eq(1000, 1000.01));
  assert.ok(eq(0, 5e-7), 'within the absolute floor');
  assert.ok(!eq(0, 1e-6));
  assert.equal(evalBlock('condition', { a: 0.1 + 0.2, b: 0.3, true: 10, false: -10 }, { op: 1 }).out, -10, 'Not Equal is its complement');
});

test('routing blocks', () => {
  assert.deepEqual(evalBlock('data_router_2', { in: 4 }), { a: 4, b: 4 });
  assert.deepEqual(evalBlock('data_router_4', { in: 4 }), { a: 4, b: 4, c: 4, d: 4 });
  assert.deepEqual(evalBlock('sign_splitter', { in: 3 }), { pos: 3, neg: 0 });
  assert.deepEqual(evalBlock('sign_splitter', { in: -3 }), { pos: 0, neg: 3 });
  assert.deepEqual(evalBlock('datameter', { in: 6 }), { out: 6 });

  const r3 = (sel) => evalBlock('data_redirector_3', { sel, a: 1, b: 2, c: 3 }).out;
  assert.deepEqual([r3(0), r3(0.2), r3(0.5), r3(0.74), r3(1), r3(5), r3(-5)], [1, 1, 2, 2, 3, 3, 1]);

  const hub = (channel) => evalBlock('data_hub', { channel, i0: 10, i1: 11, i2: 12, i3: 13, i4: 14 }).out;
  assert.deepEqual([0, 1, 2, 3, 4].map(hub), [10, 11, 12, 13, 14]);
  assert.equal(hub(-2), 10, 'channel clamps low');
  assert.equal(hub(9), 14, 'channel clamps high');
  assert.equal(hub(2.4), 12, 'channel rounds');
});

// ---- stateful blocks ------------------------------------------------------
test('accumulator outputs the new total on the tick it adds', () => {
  assert.deepEqual(runStateful('accumulator', { mode: 0 }, { in: [1, 2, 3, 4] }), [1, 3, 6, 10]);
});

test('accumulator continuous mode: total held at 0 while reset is high', () => {
  const out = runStateful('accumulator', { mode: 0 }, {
    in:    [1, 1, 1, 1, 1, 1],
    reset: [0, 0, 1, 1, 0, 0],
  });
  assert.deepEqual(out, [1, 2, 0, 0, 1, 2]);
});

test('accumulator pulse mode: resets on the rising edge only', () => {
  const out = runStateful('accumulator', { mode: 1 }, {
    in:    [1, 1, 1, 1, 1, 1],
    reset: [0, 0, 1, 1, 1, 0],
  });
  assert.deepEqual(out, [1, 2, 0, 1, 2, 3]);
});

test('memory continuous mode: tracks value while set is high', () => {
  const out = runStateful('memory', { mode: 0 }, {
    value: [5, 6, 7, 8, 9],
    set:   [1, 1, 0, 0, 1],
  });
  assert.deepEqual(out, [5, 6, 6, 6, 9]);
});

test('memory pulse mode: latches on the rising edge only', () => {
  const out = runStateful('memory', { mode: 1 }, {
    value: [5, 6, 7, 8, 9, 10],
    set:   [1, 1, 0, 1, 1, 0],
  });
  assert.deepEqual(out, [5, 5, 5, 8, 8, 8]);
});

test("delay: total latency is exactly N ticks, the block's own tick included (game code)", () => {
  assert.deepEqual(runStateful('delay', { ticks: 1 }, { in: [1, 2, 3, 4] }), [1, 2, 3, 4]);
  assert.deepEqual(runStateful('delay', { ticks: 3 }, { in: [1, 2, 3, 4, 5] }), [0, 0, 1, 2, 3]);
});

test('delay: ticks clamp to 1..60', () => {
  const lagOf = (ticks) => {
    const seq = Array.from({ length: 80 }, (_, i) => i + 1);
    return runStateful('delay', { ticks }, { in: seq }).findIndex((v) => v !== 0);
  };
  assert.equal(lagOf(0), 0);
  assert.equal(lagOf(60), 59);
  assert.equal(lagOf(500), 59);
});

test('differentiator: every interval ticks, input minus input at the last update; holds in between', () => {
  assert.deepEqual(runStateful('differentiator', { interval: 1 }, { in: [0, 2, 6, 6] }), [0, 2, 4, 0]);
  assert.deepEqual(runStateful('differentiator', { interval: 2 }, { in: [0, 2, 6, 6, 6] }), [0, 2, 2, 4, 4]);
});

test('differentiator: intervals snap to the 12 the game offers', () => {
  const { DIFF_INTERVALS } = require('../engine.js');
  assert.deepEqual(DIFF_INTERVALS, [1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60]);
  const firstUpdate = (interval) => {
    const seq = Array.from({ length: 40 }, () => 1);
    return runStateful('differentiator', { interval }, { in: seq }).findIndex((v) => v !== 0);
  };
  assert.equal(firstUpdate(8), firstUpdate(6), '8 snaps down to 6 (tie goes to the shorter)');
  assert.equal(firstUpdate(9), firstUpdate(10));
});

test('initializer: outputs 0 until its tick count has passed, then the input', () => {
  const e = build({ c: ['constant', { value: 5 }], init: ['initializer', { ticks: 4 }] }, ['c.out init.in']);
  const seq = [];
  for (let t = 0; t < 6; t++) { e.step(); seq.push(e.snapshot().init.out); }
  assert.deepEqual(seq, [0, 0, 0, 0, 5, 5]);
});

test("initializer: ticks range 0..59 like the game's 60-position knob", () => {
  const firstPass = (ticks) => {
    const e = build({ c: ['constant', { value: 5 }], init: ['initializer', { ticks }] }, ['c.out init.in']);
    for (let t = 0; t < 80; t++) { e.step(); if (e.snapshot().init.out === 5) return t; }
    return -1;
  };
  assert.equal(firstPass(0), 1, '0 suppresses nothing; the constant itself needs a tick');
  assert.equal(firstPass(4), 4);
  assert.equal(firstPass(500), 59);
});

test('state persists across step() calls and step(n) equals n single steps', () => {
  const mk = () => build({ one: ['constant', { value: 1 }], acc: ['accumulator'] }, ['one.out acc.in']);
  const a = mk(); a.step(10);
  const b = mk(); for (let i = 0; i < 10; i++) b.step();
  assert.equal(a.snapshot().acc.out, b.snapshot().acc.out);
  assert.equal(a.tick, 10);
});

test('every TYPES entry has a handler', () => {
  for (const type_id of Object.keys(TYPES)) {
    assert.doesNotThrow(() => build({ x: [type_id] }).step(2), type_id);
  }
});

// ---- circuits -------------------------------------------------------------
const SETTLE = 40; // ticks — comfortably longer than any path in these circuits
const { fly } = require('../tools/flight_harness.js');
const HOP = loadCircuit('planet_hop_v2.json');

// Hold the circuit's inputs fixed and read its outputs once settled.
function planetHop(inputs) {
  const e = new CircuitEngine(HOP);
  for (const [id, value] of Object.entries(inputs)) e.instances.get(id).params.value = value;
  e.step(SETTLE);
  return e.snapshot();
}
const STILL = { in_distance: 10000, in_accel: 0, in_velocity: 100, in_thrust_ratio: 1, in_gravity: 0, in_enable: 1 };

// A clean stop: short of the surface, thrusters off, not drifting away.
function assertStopped(r, label) {
  assert.equal(r.outcome, 'stopped', `${label}: ${JSON.stringify({ ...r, log: undefined })}`);
  assert.ok(r.distance > 40 && r.distance < 100, `${label}: stopped ${r.distance} m out`);
  assert.ok(Math.abs(r.velocity) < 1, `${label}: ${r.velocity} m/s at cut-off`);
}

test('circuits: no constant duplicates a Condition default (B = 0, True = 1, False = 0)', () => {
  for (const file of ['planet_hop_v2.json', 'raster_sweep.json', 'raster_sweep_v2.json', 'raster_sweep_v3.json']) {
    const d = loadCircuit(file);
    const byId = Object.fromEntries(d.instances.map((n) => [n.id, n]));
    for (const e of d.edges) {
      const src = byId[e.from_instance], dst = byId[e.to_instance];
      if (src.type_id !== 'constant' || dst.type_id !== 'condition') continue;
      const v = src.parameters.value;
      const redundant = (e.to_port === 'b' && v === 0) || (e.to_port === 'true' && v === 1) || (e.to_port === 'false' && v === 0);
      assert.ok(!redundant, `${file}: ${e.from_instance} (${v}) → ${e.to_instance}.${e.to_port} repeats the default`);
    }
  }
});

test('planet_hop_v2: arrives from rest and stops short of the surface', () => {
  assertStopped(fly(HOP, { velocity: 0 }), 'from rest');
});

test('planet_hop_v2: already moving when enabled, it still stops (the reported crash)', () => {
  for (const v0 of [300, 1000]) assertStopped(fly(HOP, { velocity: v0 }), `v0 = ${v0}`);
  assertStopped(fly(HOP, { velocity: 2000, distance: 300000 }), 'v0 = 2000');
  assertStopped(fly(HOP, { velocity: 800, enableAtTick: 1200 }), 'enabled mid-coast');
});

test('planet_hop_v2: works whichever way the accelerometer and velocity meter report', () => {
  assertStopped(fly(HOP, { velocity: 500, accelerometer: 'magnitude' }), 'magnitude accelerometer');
  assertStopped(fly(HOP, { velocity: 500, velocityMeter: 'signed' }), 'signed velocity meter');
});

test('planet_hop_v2: uneven forward/reverse thrust, unknown ratio, and gravity', () => {
  assertStopped(fly(HOP, { velocity: 300, ratio: 2 }), 'reverse thrust half of forward');
  assertStopped(fly(HOP, { ratioInput: 0 }), 'ratio input 0 = assume 1');
  assertStopped(fly(HOP, { velocity: 300, gravity: 5 }), 'gravity 5 m/s²');
  assertStopped(fly(HOP, { gravity: 15 }), 'gravity 15 m/s² against 20 m/s² of thrust');
});

test('planet_hop_v2: once stopped the thrusters stay off, so the ship never reverses away', () => {
  const e = new CircuitEngine(HOP);
  const set = (id, value) => { e.instances.get(id).params.value = value; };
  let distance = 20000, velocity = 0, thrust = 0, stoppedAt = null;
  for (let tick = 0; tick < 60 * 120; tick++) {
    set('in_distance', distance); set('in_velocity', Math.abs(velocity));
    set('in_accel', thrust); set('in_thrust_ratio', 1); set('in_gravity', 0); set('in_enable', 1);
    e.step();
    const cmd = e.snapshot().thruster_out.out;
    thrust = cmd * 20;
    velocity += thrust / 60;
    distance -= velocity / 60;
    if (stoppedAt === null && e.snapshot().arrived.out === 1) stoppedAt = tick;
    if (stoppedAt !== null && tick > stoppedAt + 2) assert.equal(Math.abs(cmd), 0, `thruster fired ${tick - stoppedAt} ticks after stopping`);
  }
  assert.ok(stoppedAt !== null, 'reached a stop');
  assert.ok(Math.abs(velocity) < 1, `drift after a minute: ${velocity} m/s`);
});

test('planet_hop_v2: switching enable off clears "arrived"; on again re-checks and stays put', () => {
  const e = new CircuitEngine(HOP);
  const set = (id, value) => { e.instances.get(id).params.value = value; };
  set('in_distance', 50); set('in_velocity', 0); set('in_accel', 0); set('in_thrust_ratio', 1);
  e.step(60);
  assert.equal(e.snapshot().arrived.out, 1, 'at the standoff with no speed: arrived');
  set('in_enable', 0); e.step(20);
  assert.equal(e.snapshot().arrived.out, 0);
  assert.equal(Math.abs(e.snapshot().thruster_out.out), 0);
  set('in_enable', 1); e.step(60);
  assert.equal(e.snapshot().arrived.out, 1);
  assert.equal(Math.abs(e.snapshot().thruster_out.out), 0);
});

test('planet_hop_v2: the initializer holds the thruster at 0 while the circuit settles', () => {
  const e = new CircuitEngine(HOP); // default inputs: far away, very fast, braking estimate unknown
  for (let t = 0; t < 11; t++) { e.step(); assert.equal(Math.abs(e.snapshot().thruster_out.out), 0, `tick ${t + 1}`); }
});

test('planet_hop_v2: enable off zeroes the thruster', () => {
  assert.equal(Math.abs(planetHop({ ...STILL, in_enable: 0 }).thruster_out.out), 0);
});

test('planet_hop_v2: with the braking estimate unknown and the ship moving, it brakes first', () => {
  // accelerometer reads 0 while coasting: plan on the 0.01 m/s² floor → stop at once
  assert.equal(planetHop(STILL).thruster_out.out, -1);
});

test('planet_hop_v2: time to arrival is distance ÷ speed, and safe at 0 m/s', () => {
  assert.equal(planetHop(STILL).time_to_arrival.out, 100);
  assert.equal(planetHop({ ...STILL, in_distance: 1, in_velocity: 0 }).time_to_arrival.out, 100);
});

function rasterTrace(ticks, overrides = {}) {
  const e = new CircuitEngine(loadCircuit('raster_sweep.json'));
  for (const [id, value] of Object.entries(overrides)) e.instances.get(id).params.value = value;
  const yaw = [], pitch = [];
  for (let t = 0; t < ticks; t++) {
    e.step();
    const s = e.snapshot();
    yaw.push(s.yaw_cmd.out);
    pitch.push(s.pitch_cmd.out);
  }
  return { yaw, pitch };
}
const wraps = (yaw) => yaw.flatMap((y, i) => (i > 0 && y < yaw[i - 1] ? [i] : []));

test('raster_sweep: yaw is a 0..358 sawtooth with a period of range/step ticks', () => {
  const { yaw } = rasterTrace(800);
  const w = wraps(yaw);
  assert.ok(w.length >= 3);
  assert.equal(w[1] - w[0], 180);
  assert.equal(w[2] - w[1], 180);
  assert.deepEqual(yaw.slice(w[0], w[0] + 3), [0, 2, 4]);
  assert.equal(yaw[w[0] - 1], 358);
  assert.equal(Math.max(...yaw), 358);
});

test('raster_sweep: pitch steps on exactly the tick yaw wraps', () => {
  const { yaw, pitch } = rasterTrace(1500);
  const live = wraps(yaw)[0] - 180; // first tick the outputs carry real data
  const pitchChanges = pitch.flatMap((p, i) => (i > live && p !== pitch[i - 1] ? [i] : []));
  assert.deepEqual(pitchChanges.slice(0, 7), wraps(yaw).slice(0, 7));
});

test('raster_sweep: pitch walks -60..+60 in 7 rows, then the frame repeats', () => {
  const { yaw, pitch } = rasterTrace(180 * 9);
  const w = [wraps(yaw)[0] - 180, ...wraps(yaw)];
  const rows = w.slice(0, 8).map((t) => pitch[t]);
  assert.deepEqual(rows, [-60, -40, -20, 0, 20, 40, 60, -60]);
  for (let r = 0; r < 7; r++) {
    const row = pitch.slice(w[r], w[r + 1]);
    assert.ok(row.every((p) => p === rows[r]), `pitch constant across row ${r}`);
  }
  assert.ok(pitch.every((p) => p >= -60 && p <= 60), 'never leaves the ±60° band');
});

test('raster_sweep: a pitch step that does not divide the span still stays in band', () => {
  const { pitch } = rasterTrace(180 * 10, { in_pitch_step: 50 });
  const live = pitch.slice(20);
  assert.deepEqual([...new Set(live)].sort((a, b) => a - b), [-60, -10, 40]);
});

test('raster_sweep: yaw offset rotates the sweep and wraps at 360', () => {
  const { yaw } = rasterTrace(400, { in_yaw_offset: 90 });
  const live = yaw.slice(20);
  assert.ok(live.includes(90) && live.includes(0) && live.includes(358));
  assert.ok(live.every((y) => y >= 0 && y < 360));
});

test('raster_sweep: enable off freezes both axes', () => {
  const { yaw, pitch } = rasterTrace(500, { in_enable: 0 });
  assert.ok(yaw.every((y) => y === 0));
  assert.ok(pitch.slice(20).every((p) => p === -60));
});

// ---- the single-file simulator page --------------------------------------
test('circuit-simulator.html embeds the current engine.js and demo circuit', () => {
  const { execFileSync } = require('node:child_process');
  assert.doesNotThrow(
    () => execFileSync(process.execPath, [path.join(__dirname, '..', 'tools', 'sync-simulator.js'), '--check'], { stdio: 'pipe' }),
    'run: node tools/sync-simulator.js',
  );
});

// ---- game parts beyond logic: ports, power, wireless ------------------------
const PART_TEXT = require('../tools/part_text.json');

test('every part has the same ports as the game lists, in game order', () => {
  for (const [type_id, def] of Object.entries(TYPES)) {
    if (!def.order) continue;
    const text = PART_TEXT[type_id];
    assert.ok(text, `${type_id} has in-game text`);
    for (const port of def.order) assert.ok(text.ports && text.ports[port], `${type_id}.${port} matches a game port`);
    const shared = Object.keys(def.sharedPort || {}).length;
    assert.equal(Object.keys(text.ports).length - shared, def.order.length, `${type_id}: port count`);
  }
});

test('ports of different kinds cannot be wired together', () => {
  assert.throws(() => build({ cam: ['camera'], t: ['small_electric_thruster'] }, ['cam.video t.throttle']), /Cannot wire video port/);
  assert.throws(() => build({ c: ['constant'], b: ['small_disposable_battery'] }, ['c.out b.power']), /Cannot wire data port/);
});

function powerRig() {
  return build({
    bat: ['large_disposable_battery', { capacity: 10, charge: 10 }],
    router: ['power_router'],
    gyro: ['gyro_line', { pitch: 5, roll: -2, power_ps: 60 }],
  }, ['bat.power router.a', 'router.b gyro.power']);
}

test('power: a battery through a Power Router powers a sensor and drains by P/s ÷ 60 per tick', () => {
  const e = powerRig();
  e.step(2);
  assert.deepEqual(e.snapshot().gyro, { pitch: 5, roll: -2 });
  assert.equal(e.instances.get('bat').params.charge, 8, '60 P/s draws 1 Unit per tick');
  assert.equal(e.snapshot().bat.level, 8, 'level port reports Units left');
});

test('power: an empty battery leaves the circuit unpowered and sensors read 0', () => {
  const e = powerRig();
  e.step(11);
  assert.deepEqual(e.snapshot().gyro, { pitch: 0, roll: 0 });
  assert.equal(e.status.get('gyro'), 'no power');
});

test('power: a part with no power cable is unpowered', () => {
  const e = build({ gyro: ['gyro_line', { pitch: 5 }] });
  e.step(2);
  assert.equal(e.snapshot().gyro.pitch, 0);
});

test('power: generation covers demand without touching batteries, surplus recharges', () => {
  const e = build({
    sun: ['solar_panel', { gen_ps: 120 }],
    bat: ['large_rechargeable_battery', { capacity: 100, charge: 50 }],
    r: ['power_router'],
    gyro: ['gyro_line', { pitch: 1, power_ps: 60 }],
  }, ['sun.a r.a', 'r.b bat.power', 'r.c gyro.power']);
  e.step(10);
  assert.equal(e.snapshot().gyro.pitch, 1);
  assert.equal(e.instances.get('bat').params.charge, 60, '(120 − 60) / 60 = 1 Unit per tick');
});

test('power: disposable batteries do not recharge', () => {
  const e = build({
    dyn: ['dynamo_box', { gen_ps: 600 }],
    bat: ['medium_disposable_battery', { capacity: 100, charge: 50 }],
  }, ['dyn.power bat.power']);
  e.step(10);
  assert.equal(e.instances.get('bat').params.charge, 50);
});

test('power: electric thrusters draw in proportion to throttle', () => {
  const e = build({
    bat: ['large_disposable_battery', { capacity: 100, charge: 100 }],
    lever: ['lever_vertical', { out: 0.5 }],
    t: ['large_electric_thruster', { power_ps: 120 }],
  }, ['bat.power t.power', 'lever.out t.throttle']);
  e.step(11);
  // the lever's output reaches the thruster's input after tick 1; ticks 2..11 draw 60 P/s = 1 Unit each
  assert.equal(e.instances.get('bat').params.charge, 90);
  assert.equal(e.status.get('t'), '50%');
});

test('power: gates draw only on the tick their input changes', () => {
  const e = build({
    bat: ['small_disposable_battery', { capacity: 100, charge: 100 }],
    sw: ['switch', { out: 1 }],
    g: ['small_gate', { power_ps: 60 }],
  }, ['bat.power g.power', 'sw.out g.state']);
  e.step(10);
  assert.equal(e.instances.get('bat').params.charge, 99);
});

test('power: a Fuse Box trips when the circuit draws over its limit, and stays off', () => {
  const e = build({
    bat: ['large_disposable_battery', { capacity: 1000, charge: 1000 }],
    fuse: ['fuse_box', { limit_ps: 150 }],
    a: ['radar', { power_ps: 100 }],
    r: ['power_router'],
    b: ['radar', { power_ps: 100 }],
  }, ['bat.power fuse.a', 'fuse.b r.a', 'r.b a.power', 'r.c b.power']);
  e.step(1);
  assert.equal(e.instances.get('fuse').params.on, 0, 'tripped: 200 P/s > 150 P/s');
  e.step(1);
  assert.equal(e.status.get('a'), 'no power');
  assert.equal(e.status.get('fuse'), 'TRIPPED');
  e.instances.get('fuse').params.on = 1; // switched back on by hand: trips again
  e.step(1);
  assert.equal(e.instances.get('fuse').params.on, 0);
});

test('power: a Power Blocker splits the circuit while its input is ≥ 0.5', () => {
  const e = build({
    bat: ['large_disposable_battery', { capacity: 1000, charge: 1000 }],
    blk: ['power_blocker'],
    sw: ['switch', { out: 0 }],
    gyro: ['gyro_line', { pitch: 3 }],
  }, ['bat.power blk.a', 'blk.b gyro.power', 'sw.out blk.block']);
  e.step(3);
  assert.equal(e.snapshot().gyro.pitch, 3);
  e.instances.get('sw').params.out = 1;
  e.step(3);
  assert.equal(e.snapshot().gyro.pitch, 0);
});

test('power: generation and usage meters read their circuit', () => {
  const e = build({
    sun: ['solar_panel', { gen_ps: 40 }],
    r: ['power_router'],
    gm: ['power_generation_meter'],
    um: ['power_usage_meter'],
    rad: ['radar', { power_ps: 25 }],
  }, ['sun.a r.a', 'r.b gm.power', 'r.c um.power', 'r.d rad.power']);
  e.step(2);
  assert.equal(e.snapshot().gm.generation, 40);
  assert.equal(e.snapshot().um.usage, 25);
});

test('wireless: one transmitter per channel feeds every receiver on it', () => {
  const e = build({
    c: ['constant', { value: 7 }],
    tx: ['wireless_transmitter', { channel: 3 }],
    rx1: ['wireless_transmitter', { channel: 3 }],
    rx2: ['wireless_transmitter', { channel: 4 }],
  }, ['c.out tx.tx']);
  e.step(3);
  assert.equal(e.snapshot().rx1.rx, 7);
  assert.equal(e.snapshot().rx2.rx, 0, 'another channel hears nothing');
});

test('wireless: two transmitters on one channel conflict', () => {
  const e = build({
    c1: ['constant', { value: 1 }], c2: ['constant', { value: 2 }],
    t1: ['wireless_transmitter', { channel: 1 }], t2: ['wireless_transmitter', { channel: 1 }],
    rx: ['wireless_transmitter', { channel: 1 }],
  }, ['c1.out t1.tx', 'c2.out t2.tx']);
  e.step(3);
  assert.equal(e.snapshot().rx.rx, 0);
  assert.match(e.status.get('rx'), /CONFLICT/);
});

test('triggers latch at ≥ 0.5 (C4, TNT, Clima Bomb, decoupler)', () => {
  const e = build({ s: ['slider', { value: 0.49 }], bomb: ['bomb_c4'] }, ['s.out bomb.trigger']);
  e.step(3);
  assert.equal(e.status.get('bomb'), 'armed');
  e.instances.get('s').params.value = 0.5; e.step(2);
  e.instances.get('s').params.value = 0; e.step(2);
  assert.equal(e.status.get('bomb'), 'DETONATED');
});

test('Red Alert Light thresholds: > 0.333 light, > 0.666 light + alarm', () => {
  const at = (x) => { const e = build({ c: ['constant', { value: x }], l: ['red_alert_light'] }, ['c.out l.in']); e.step(2); return e.status.get('l'); };
  assert.deepEqual([at(0.3), at(0.5), at(0.7)], ['off', 'LIGHT', 'LIGHT + ALARM']);
});

test('video and plasma: a powered camera feeds a monitor; plasma feeds a shield', () => {
  const e = build({
    bat: ['large_disposable_battery', { capacity: 1000, charge: 1000 }],
    r: ['power_router'],
    cam: ['camera'], mon: ['monitor_crt'],
    pg: ['small_plasma_generator'], one: ['constant', { value: 1 }],
    sh: ['wind_shield_generator', { max_wind: 80 }],
  }, ['bat.power r.a', 'r.b cam.power', 'r.c mon.power', 'r.d pg.power', 'cam.video mon.video', 'one.out pg.speed', 'pg.plasma sh.plasma']);
  e.step(4);
  assert.equal(e.status.get('mon'), 'showing video');
  assert.equal(e.snapshot().sh.max_wind, 80);
});

test('BPS (game code): indicator = clamp(log2(distance / stopping distance) / 6, ±1), eased in by 1 − e^−0.15 a tick', () => {
  const near = (x, y) => Math.abs(x - y) < 1e-6;
  const at = (d, v, a) => {
    const e = build({ d: ['constant', { value: d }], v: ['constant', { value: v }], a: ['constant', { value: a }], b: ['braking_point_system'] },
      ['d.out b.distance', 'v.out b.velocity', 'a.out b.acceleration']);
    e.step(200); return e.snapshot().b.indicator;          // long enough for the easing to settle
  };
  // At 100 m/s and 10 m/s² the stopping distance v²/2a is 500 m.
  for (const [d, v, a, want] of [
    [500, 100, 10, 0], [250, 100, 10, -1 / 6], [1000, 100, 10, 1 / 6],   // each doubling is 1/6
    [32000, 100, 10, 1], [1e6, 100, 10, 1], [500 / 64, 100, 10, -1],     // ±1 at a 64× margin, clamped beyond
    [500, -100, 10, 0], [500, 100, -10, 0],                              // signs are ignored
    [100, 0, 10, 1],                                                     // not moving: safe
    [500, 100, 0, -1], [0, 100, 10, -1],                                 // moving with no braking, or no distance left
  ]) assert.ok(near(at(d, v, a), want), `d ${d}, v ${v}, a ${a}: ${at(d, v, a)}, want ${want}`);
  // Easing: from 0 toward a steady target of 1, n ticks give 1 − e^(−0.15 n).
  const e = build({ d: ['constant', { value: 100 }], b: ['braking_point_system'] }, ['d.out b.distance']);
  e.step(1); assert.ok(near(e.snapshot().b.indicator, 1 - Math.exp(-0.15)));
  e.step(9); assert.ok(near(e.snapshot().b.indicator, 1 - Math.exp(-1.5)));
});

// ---- raster_sweep_v2: closed-loop target lock by cone probing, flown against tools/attitude_harness.js ----
const { lock } = require('../tools/attitude_harness.js');
const LOCK = loadCircuit('raster_sweep_v2.json');
const assertLocked = (r, label, maxErr = 0.1, maxT = 60) => {
  assert.equal(r.outcome, 'locked', `${label}: ${JSON.stringify({ ...r, trace: undefined })}`);
  assert.equal(r.coneDeg, 1, `${label}: cone ${r.coneDeg}`);
  assert.ok(r.err < maxErr, `${label}: ${r.err}° off the target's centre`);
  assert.ok(r.t < maxT, `${label}: took ${r.t} s`);
};

test('raster_sweep_v2: from a wide cone it centres on the target with the 1° cone, within 0.1°', () => {
  assertLocked(lock(LOCK, {}), '8°/-5° off, 30° cone');
  assertLocked(lock(LOCK, { coneManual: 0, targets: [{ yaw: 18, pitch: -12, radius: 0.2, distance: 5e7 }] }), '50° cone, 21° off');
});

test('raster_sweep_v2: works for weak and strong RCS, and with tune_rcs off by 2x either way', () => {
  for (const [alpha, setting] of [[5, 5], [60, 60], [40, 20], [10, 20]]) {
    assertLocked(lock(LOCK, { alpha, rcsSetting: setting }), `alpha ${alpha}, tune_rcs ${setting}`);
  }
});

test('raster_sweep_v2: a big close planet is centred too (its disk counts once any of it is in the cone)', () => {
  assertLocked(lock(LOCK, { targets: [{ yaw: -10, pitch: 7, radius: 6, distance: 4e5 }] }), 'radius 6°');
});

test('raster_sweep_v2: other bodies, farther or nearer, never pull it off the remembered target', () => {
  for (const d of [9e6, 9e5]) {
    assertLocked(lock(LOCK, { targets: [{ yaw: 6, pitch: 4, radius: 0.4, distance: 3e6 }, { yaw: 30, pitch: 2, radius: 1, distance: d }] }),
      `second body at ${d} m`);
  }
});

test('raster_sweep_v2: copes with an RCS deadband and rotometer noise', () => {
  assertLocked(lock(LOCK, { deadband: 0.05 }), 'deadband 0.05', 0.1, 120);
  assertLocked(lock(LOCK, { rateNoise: 0.2 }), 'noise 0.2 deg/s');
});

test('raster_sweep_v2: moving the joystick hands control straight back', () => {
  const r = lock(LOCK, { joystick: (tick) => (tick > 600 ? [0.8, 0] : [0, 0]) });
  assert.equal(r.outcome, 'manual');
  assert.ok(r.t > 10 && r.t < 10.5, `back to manual at ${r.t} s`);
});

test('raster_sweep_v2: with nothing in the cone at Start it gives up after about 10 s', () => {
  const r = lock(LOCK, { targets: [{ yaw: 60, pitch: 0, radius: 0.3, distance: 2e6 }] });
  assert.equal(r.outcome, 'manual');
  assert.ok(r.t > 9 && r.t < 12, `gave up at ${r.t} s`);
});

// ---- raster_sweep_v3: the compact lock (cone tracker + coordinate descent), same harness ----
const LOCK3 = loadCircuit('raster_sweep_v3.json');
// locked = the 1° cone sees the target (nose within 0.5° of its disk) and the ship is still, for 1 s
const lock3 = (opts) => lock(LOCK3, { startAt: 90, damp: 0.25, maxTicks: 60 * 120, ...opts });
const assertLocked3 = (r, label, radius = 0.3, maxT = 60) => {
  assert.equal(r.outcome, 'locked', `${label}: ${JSON.stringify({ ...r, trace: undefined })}`);
  assert.ok(r.err <= radius + 0.5, `${label}: ${r.err}° off the target's centre`);
  assert.ok(r.t < maxT, `${label}: took ${r.t} s`);
};

test('raster_sweep_v3: under 40 blocks, sensors and controls not counted', () => {
  const logic = LOCK3.instances.filter((n) => !['slider', 'toggle'].includes(n.type_id));
  assert.ok(logic.length < 40, `${logic.length} blocks`);
});

test('raster_sweep_v3: in manual the stick drives the RCS directly and the lever sets the cone', () => {
  const e = new CircuitEngine(LOCK3);
  const set = (id, v) => { e.instances.get(id).params.value = v; };
  set('in_auto', 0); set('in_joy_yaw', 0.7); set('in_joy_pitch', -0.4); set('in_yaw_rate', 12); set('in_pitch_rate', -3);
  set('in_cone_manual', 0.3); set('in_scan_dist', 2e6);
  e.step(20);
  const s = e.snapshot();
  const near = (a, b) => Math.abs(a - b) < 1e-9;
  assert.ok(near(s.rcs_yaw.out, 0.7) && near(s.rcs_pitch.out, -0.4), `rcs ${s.rcs_yaw.out}, ${s.rcs_pitch.out}`);
  assert.ok(near(s.cone_cmd.out, 1.02 - 0.3), `cone ${s.cone_cmd.out}`);
});

test('raster_sweep_v3: locks with the 1° cone, from a 30° or a 50° cone', () => {
  assertLocked3(lock3({}), '8°/-5° off, 30° cone');
  assertLocked3(lock3({ coneManual: 0, targets: [{ yaw: 12, pitch: -9, radius: 0.2, distance: 5e7 }] }), '50° cone, 15° off', 0.2);
});

test('raster_sweep_v3: one tuning value, D ≈ 5 / (deg/s² at full stick), covers weak to very agile ships', () => {
  for (const alpha of [5, 20, 100]) assertLocked3(lock3({ alpha, damp: 5 / alpha }), `alpha ${alpha}`);
  assertLocked3(lock3({ alpha: 5, damp: 0.25 }), 'alpha 5 with D tuned for 20');
});

test('raster_sweep_v3: a big close planet ends with the 1° cone on its disk', () => {
  assertLocked3(lock3({ targets: [{ yaw: -10, pitch: 7, radius: 6, distance: 4e5 }] }), 'radius 6°', 6);
});

test('raster_sweep_v3: other bodies, farther or nearer, do not pull it off the remembered target', () => {
  for (const d of [9e6, 9e5]) {
    assertLocked3(lock3({ targets: [{ yaw: 6, pitch: 4, radius: 0.4, distance: 3e6 }, { yaw: 30, pitch: 2, radius: 1, distance: d }] }),
      `second body at ${d} m`, 0.4);
  }
});

test('raster_sweep_v3: copes with rotometer noise plus 3 ticks of scanner lag', () => {
  assertLocked3(lock3({ rateNoise: 0.2, scanDelay: 3 }), 'noise and lag');
});
