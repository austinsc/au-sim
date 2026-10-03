'use strict';
// Blueprint generator: I/O rows (bundle / split) and the simulator page that embeds the generator.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const { generate } = require('../bpgen.js');

const ROOT = path.join(__dirname, '..');
const load = (f) => JSON.parse(fs.readFileSync(path.join(ROOT, f), 'utf8'));

test('circuit-simulator.html: every script on the page, and the embedded generator, parses', () => {
  const html = fs.readFileSync(path.join(ROOT, 'circuit-simulator.html'), 'utf8');
  const re = /<script([^>]*)>([\s\S]*?)<\/script>/g;
  let m, n = 0;
  while ((m = re.exec(html))) {
    if (/src=/.test(m[1])) continue;
    n++;
    assert.doesNotThrow(() => new Function(m[2]), `script #${n} (${m[1].trim() || 'inline'})`);
  }
  assert.ok(n >= 2, 'expected the page script and the embedded generator');
});

test('bundle: every stub ends in one row of parallel cables on the -z face, each beside its label', () => {
  // a box and seed known to work (found by tools/make_blueprint.js)
  const out = generate(load('circuits/gen_test_settings.json'), { io: 'bundle', box: [12, 8, 4], seed: 5, deterministic: true, timeBudgetMs: 1e9 });
  const r = out.report;
  assert.strictEqual(r.io, 'bundle');
  assert.strictEqual(r.buses.length, 1);
  assert.strictEqual(r.buses[0].face, '-z');
  assert.strictEqual(r.buses[0].ends.length, r.stubs.length);
  // the end cells: on z = 0, open toward -z, straight, in at most two rows, two cells apart within a row
  const ends = out.layout.cables.filter((c) => c.role !== 'net' && c.open.includes(5) && c.cell[2] === 0);
  assert.strictEqual(ends.length, r.stubs.length);
  for (const c of ends) assert.strictEqual(c.shape, 0, 'the end cell is a straight cable');
  const rows = [...new Set(ends.map((c) => c.cell[1]))];
  assert.ok(rows.length <= r.buses[0].rows);
  for (const y of rows) {
    const xs = ends.filter((c) => c.cell[1] === y).map((c) => c.cell[0]).sort((a, b) => a - b);
    for (let i = 1; i < xs.length; i++) assert.ok(xs[i] - xs[i - 1] >= 2, 'one label width between ends');
  }
});

test('split: inputs leave through -z and outputs through +z, each group in a row', () => {
  const out = generate(load('circuits/gen_test_basic.json'), { io: 'split', seed: 1, deterministic: true, timeBudgetMs: 1e9 });
  const r = out.report;
  assert.strictEqual(r.io, 'split');
  for (const s of r.stubs) assert.strictEqual(s.face, s.io === 'in' ? '-z' : '+z');
  for (const b of r.buses) for (const label of b.ends) assert.strictEqual(r.stubs.find((s) => s.label === label).face, b.face);
});

test('flat: one layer of upright parts on a floor of frames, labels lying beside their ends, no cable over a label', () => {
  const { geometry, UPRIGHT, LYING } = require('../bpgen.js');
  // a box and seed known to work (every seed did at this size)
  const out = generate(load('circuits/gen_test_settings.json'), { flat: true, io: 'split', box: [32, 2, 8], seed: 1, deterministic: true, timeBudgetMs: 1e9 });
  const r = out.report;
  assert.ok(r.flat);
  assert.deepStrictEqual(r.floor, [Math.ceil(r.box[0] / 4), Math.ceil(r.box[2] / 4)], 'the floor covers the footprint');
  const labelTop = new Set();
  for (const p of out.layout.parts) {
    assert.strictEqual(p.o[1], 0, `${p.id} stands on the floor`);
    if (p.type.startsWith('label')) {
      assert.ok(Object.values(LYING).includes(p.k), `label ${p.id} lies face up`);
      for (const c of geometry(p.type, p.k, p.mir).cells) labelTop.add(`${p.o[0] + c[0]},${p.o[2] + c[2]}`);
    } else assert.ok(Object.values(UPRIGHT).includes(p.k), `${p.id} is upright`);
  }
  for (const c of out.layout.cables) {
    assert.ok(c.cell[1] <= 1, 'cables run on the floor or one level up');
    if (c.cell[1] === 1) assert.ok(!labelTop.has(`${c.cell[0]},${c.cell[2]}`), 'no cable lies over a label');
  }
});

test('flat without a floor: no frames, and cable reach counted from the ports', () => {
  const out = generate(load('circuits/gen_test_basic.json'), { flat: true, floor: false, seed: 1, deterministic: true, timeBudgetMs: 1e9 });
  assert.strictEqual(out.report.floor, null);
  assert.ok(out.report.longestCable <= 21);
  for (const p of out.layout.parts) assert.strictEqual(p.o[1], 0);
});
