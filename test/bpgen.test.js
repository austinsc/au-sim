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
