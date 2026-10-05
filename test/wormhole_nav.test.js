'use strict';
// The wormhole navigation (tools/build_wormhole_nav.js) flown against the black hole model (tools/wormhole_harness.js).
const test = require('node:test');
const assert = require('node:assert');
const { diagram } = require('../tools/build_wormhole_nav.js');
const { fly } = require('../tools/wormhole_harness.js');

const ok = (c, r, want) => assert.ok(r.outcome === want, `${JSON.stringify(c)}: ${JSON.stringify(r)}`);

test('wormhole nav: burns in, turns, brakes and holds where gravity is half its thrust, strain-free', () => {
  const c = { aMax: 6, r: 15000e3 };
  const r = fly(diagram, c);
  ok(c, r, 'holding');
  assert.ok(Math.abs(r.gHold - 0.6 * 0.8 * 6) < 0.05, JSON.stringify(r));     // hold at c_hold · c_brake · a
  assert.ok(r.strainS === 0 && r.maxPart < 10.39, JSON.stringify(r));          // never over the strain threshold
  assert.ok(r.flipAt > 60 && r.peakV > 1000, JSON.stringify(r));               // it burned in before turning
});

test('wormhole nav: started inside its hold point it turns and hovers where it is, any signs', () => {
  for (const [rcsSign, rotSign] of [[1, 1], [-1, 1], [1, -1]]) {
    const c = { aMax: 6, r: 8000e3, rcsSign, rotSign };
    const r = fly(diagram, c);
    ok(c, r, 'holding');
    assert.ok(Math.abs(r.rKm - 8000) < 100 && r.strainS <= 4, JSON.stringify(r));   // only the 3 s measurement burn
  }
});

test('wormhole nav: Descend off again mid-descent brakes and holds wherever it still can', () => {
  const c = { aMax: 6, r: 15000e3, descendAt: 'hold', descendFor: 300 };
  const r = fly(diagram, c);
  ok(c, r, 'held again');
  assert.ok(r.strainS === 0 && r.rKm < 11180, JSON.stringify(r));
});
