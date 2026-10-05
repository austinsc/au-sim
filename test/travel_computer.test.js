'use strict';
// The travel computer (tools/build_travel_computer.js) flown against its 1-D model (tools/travel_harness.js), with the
// user's ship (8,279,000 N forward on the mains, 4,374,000 N reverse, most of it fuel engines that take 10–20 s to
// respond; 6 SRBs of 950,000 N) on trips of 250,000 km.
const test = require('node:test');
const assert = require('node:assert');
const { diagram, TUNE } = require('../tools/build_travel_computer.js');
const { fly, mixedShip } = require('../tools/travel_harness.js');

const D = 250e6;
const STRAIN = 10.39;   // m/s²: the game strains joints above this net acceleration
const arrive = (c) => {
  const r = fly(diagram, c);
  assert.ok(r.outcome === 'arrived' && Math.abs(r.err) < 6, `${JSON.stringify(c)}: ${JSON.stringify(r)}`);
  return r;
};
const exact = (r, M) => assert.ok(Math.abs(r.aBrk / (TUNE.margin * 4374e3 / M) - 1) < 0.01, JSON.stringify(r));

test('travel computer: measures its braking gently, and keeps the whole trip under the strain limit', () => {
  const r = arrive({ ...mixedShip(300e3, 24e3), d: D });
  exact(r, 300e3);
  assert.ok(r.maxAcc < STRAIN, `peak ${r.maxAcc} m/s²`);
  assert.ok(r.srbOn === null, 'mains and SRBs at full (47 m/s²) do not fit under MAX ACCEL: they stay dark');
});

test('travel computer: with room under MAX ACCEL it lights the SRBs at once and drops them at burnout', () => {
  const r = arrive({ ...mixedShip(300e3, 24e3), d: D, maxAccel: 50 });
  assert.ok(r.srbOn <= 9 && r.srbOff === 1015, JSON.stringify(r));
  assert.ok(r.maxAcc < 1.15 * 50, `peak ${r.maxAcc} m/s²`);
});

test('travel computer: climbs away from a planet beneath it (its pull from behind), strain-free', () => {
  const r = arrive({ ...mixedShip(300e3, 24e3), d: D, dep: { R: 300e3, g0: 9.8, h: 2e3 } });
  assert.ok(r.maxAcc < STRAIN, `peak ${r.maxAcc} m/s²`);
});

test('travel computer: holds until the scanner sees the target', () => {
  const r = arrive({ ...mixedShip(300e3, 24e3), d: D, maxAccel: 50, blindUntil: 20 });
  assert.ok(r.srbOn >= 20, JSON.stringify(r));
});
