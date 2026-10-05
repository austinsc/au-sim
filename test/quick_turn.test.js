'use strict';
// The button-activated 180° turn (tools/build_quick_turn.js) flown against its yaw model.
const test = require('node:test');
const assert = require('node:assert');
const { diagram, turn } = require('../tools/build_quick_turn.js');

test('quick turn: 180° on one press, coasting, any sign, thrust suppressed only while turning', () => {
  for (const alpha of [4, 16, 64])
    for (const [rcsSign, rotSign] of [[1, 1], [-1, 1], [1, -1], [-1, -1]]) {
      const r = turn(diagram, { alpha, rcsSign, rotSign });
      const tag = `alpha ${alpha}, signs ${rcsSign}/${rotSign}: ${JSON.stringify(r)}`;
      assert.ok(r.ok && Math.abs(r.turned - 180) < 1 && Math.abs(r.drift) < 0.3, tag);
      assert.ok(r.overshoot < 6 && r.time < 25, tag);
      assert.strictEqual(r.yawBeforeTurn, 0, tag);
      assert.ok(r.enableOffFrom <= 3, tag);
    }
});

test('quick turn: hovering (gimballed thrusters drag the yaw rate to alpha · u) settles without ringing', () => {
  for (const alpha of [3, 16, 64])
    for (const k of [0.5, 1, 3]) {
      const r = turn(diagram, { alpha, pull: k * alpha });
      assert.ok(r.ok && r.overshoot < 1 && r.reversals < 20, `alpha ${alpha}, pull ${k}x: ${JSON.stringify(r)}`);
    }
});

test('quick turn: every press turns (one that settled within 0.15° of 180° used to end the next turn at once)', () => {
  for (const c of [{ alpha: 8, pull: 8, turns: 3 }, { alpha: 24, turns: 3 }]) {
    const r = turn(diagram, c);
    assert.ok(r.ok && r.time > 5, `${JSON.stringify(c)}: ${JSON.stringify(r)}`);
  }
});
