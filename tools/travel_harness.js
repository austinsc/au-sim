'use strict';
// 1-D flight model for circuits/travel_computer.json (tools/build_travel_computer.js).
//
//   line      d: metres from the ship to the target's surface; v: closing speed (m/s)
//   gravity   the target's, toward it: g0 · (R / (R + d))²; and, with dep: { R, g0, h }, a planet the ship is leaving,
//             straight behind it, h metres above its surface (0 = landed on it): dep.g0 · (dep.R / (dep.R + h))², away
//   ground    landed, the ship stays put while the net acceleration points into the ground; coming back down is
//             logged as a bump (its speed), or as 'crashed' over 10 m/s. hover: the ship's own lift system holds it
//             against that planet's pull until the computer starts flying
//   engines   THRUST CTL (ch 1) c in −1..1, after delayTicks: forward thrusters slew toward max(c, 0), reverse ones
//             (Reversed Input) toward max(−c, 0), each at 1 / acceleration time per second; aFwd, aRev m/s² at full.
//             groups: { fwd: [[m/s², acceleration time s], ...], rev: [...] } instead gives each kind its own slew
//             (fuel thrusters take 10–30 s, electrics 0.2–0.95 s)
//   SRBs      SOLID + (ch 35) ≥ 0.5 for 60 ticks in a row ignites them (the game's ignition); their thrust then ramps
//             at 1/5 per second (acceleration time 5 s) to aSrb, holds until 1000 s after ignition and ramps down again.
//             SOLID − (ch 36) ≥ 0.5 ejects them: their thrust leaves with them, and the ship's other accelerations grow
//             by massRatio (the ship is that much lighter)
//   sensors   FWD DIST (ch 30) d, or 1e20 if blind; Z SPEED (ch 23) v smoothed out += (new − out) · 0.1535 a tick; the
//             Gravitymeter |net gravity|
//
// fly(diagram, opts) -> { outcome: 'arrived' | 'impact' | 'crashed' | 'reversing' | 'timeout' | 'held short', ... }
//   arrived: within 2% of the standoff (5 m at least) and under 1 m/s for 10 s; err = d − standoff, tArrive from
//   Autopilot on; aBrk: the braking the circuit measured and plans on, against margin · aRev; maxAcc: the largest net
//   acceleration (what strains the game's joints, gravity included), maxAccFly the same after the measurement;
//   opts.maxAccel sets the MAX ACCEL Constant
const { CircuitEngine } = require('../engine.js');
const { TUNE } = require('./build_travel_computer.js');

function fly(diagram, opts = {}) {
  const o = {
    d: 2e6, v: 0, R: 300e3, g0: 9.8, dep: null, aFwd: 20, aRev: 20 / TUNE.thrust_ratio, aSrb: 0, massRatio: 1,
    slewF: 1 / 0.7, slewR: 1 / 0.7, delayTicks: 4, lever: 0.3, engageAt: 30, blindUntil: 0,
    maxTicks: 60 * 3600 * 24, ...opts,
  };
  const d2 = JSON.parse(JSON.stringify(diagram));
  for (const [ch, name] of [[30, 'dist'], [23, 'vz']]) {
    d2.instances.push({ id: `ext_${name}`, type_id: 'slider', parameters: { value: 0 }, position: { x: 0, y: 0 } });
    d2.instances.push({ id: `ext_${name}_tx`, type_id: 'wireless_transmitter', parameters: { channel: ch }, position: { x: 0, y: 0 } });
    d2.edges.push({ from_instance: `ext_${name}`, from_port: 'out', to_instance: `ext_${name}_tx`, to_port: 'tx' });
  }
  for (const [ch, id] of [[1, 'lis_thrust'], [35, 'lis_ignite'], [36, 'lis_eject']]) {
    d2.instances.push({ id, type_id: 'wireless_transmitter', parameters: { channel: ch }, position: { x: 0, y: 0 } });
  }
  const e = new CircuitEngine(d2);
  const inst = (id) => e.instances.get(id);
  inst('standoff').params.value = o.lever;
  if (o.maxAccel !== undefined) inst('max_accel').params.value = o.maxAccel;   // the MAX ACCEL Constant
  const standoff = 10 * 10 ** (6 * o.lever);
  let { d, v } = o;
  let h = o.dep ? o.dep.h : Infinity;
  const G = o.groups || { fwd: [[o.aFwd, 1 / o.slewF]], rev: [[o.aRev, 1 / o.slewR]] };
  const gf = G.fwd.map(() => 0), gr = G.rev.map(() => 0);
  let srb = 0, ignProgress = 0, ignitedAt = null, ejectedAt = null, k = 1;
  let vzOut = v, quietSince = null, stillSince = null, peak = 0, maxAcc = 0, maxAccFly = 0, aBrk = null, airborne = h > 0.5, bump = 0;
  const q = [];
  const dt = 1 / 60;
  const res = (outcome, tick, extra = {}) => ({
    outcome, t: +(tick / 60).toFixed(0), err: +(d - standoff).toFixed(1), v: +v.toFixed(2), peakV: Math.round(peak),
    maxAcc: +maxAcc.toFixed(1), maxAccFly: +maxAccFly.toFixed(1), aBrk: aBrk === null ? null : +aBrk.toFixed(2), srbOn: ignitedAt === null ? null : +(ignitedAt / 60).toFixed(0),
    srbOff: ejectedAt === null ? null : +(ejectedAt / 60).toFixed(0), ...(bump ? { bump: +bump.toFixed(1) } : {}), ...extra,
  });
  for (let tick = 0; tick < o.maxTicks; tick++) {
    const gT = o.g0 * (o.R / (o.R + Math.max(0, d))) ** 2;
    const gD = o.dep ? o.dep.g0 * (o.dep.R / (o.dep.R + Math.max(0, h))) ** 2 : 0;
    inst('ext_dist').params.value = tick < o.blindUntil * 60 ? 1e20 : Math.max(0, d);
    vzOut += (v - vzOut) * 0.1535;
    inst('ext_vz').params.value = vzOut;
    inst('gravitymeter').params.gravity = Math.abs(gT - gD);
    inst('autopilot').params.out = tick >= o.engageAt ? 1 : 0;
    e.step();
    const snap = e.snapshot();
    const rx = (id) => snap[id].rx ?? 0;
    if (tick === o.engageAt + TUNE.meas_ticks + 10) aBrk = snap.a_brk.out;
    q.push(rx('lis_thrust'));
    const c = q.length > o.delayTicks ? q.shift() : 0;
    // SRBs: ignition, ramps, burn, eject
    if (ignitedAt === null) {
      ignProgress = rx('lis_ignite') >= 0.5 ? ignProgress + 1 : Math.max(0, ignProgress - 1);
      if (ignProgress >= 60) ignitedAt = tick;
    }
    if (ejectedAt === null && rx('lis_eject') >= 0.5) { ejectedAt = tick; k = o.massRatio; }
    const burning = ignitedAt !== null && ejectedAt === null && tick - ignitedAt < 1000 * 60;
    srb = ejectedAt !== null ? 0 : srb + Math.max(-dt / 5, Math.min(dt / 5, (burning ? 1 : 0) - srb));
    let thrust = 0;
    G.fwd.forEach(([acc, t], j) => { gf[j] += Math.max(-dt / t, Math.min(dt / t, Math.max(0, Math.min(1, c)) - gf[j])); thrust += acc * gf[j]; });
    G.rev.forEach(([acc, t], j) => { gr[j] += Math.max(-dt / t, Math.min(dt / t, Math.max(0, Math.min(1, -c)) - gr[j])); thrust -= acc * gr[j]; });
    let a = k * thrust + o.aSrb * srb + gT - gD;   // closing acceleration
    if (o.hover && tick < o.engageAt + TUNE.meas_ticks + TUNE.fly_delay) a += gD;   // the ship's own hover holds it
    if (o.dep && h <= 0 && v <= 0 && a <= 0) { a = 0; v = 0; }            // resting on the ground
    v += a * dt;
    d -= v * dt;
    if (o.dep) {
      h += v * dt;
      if (h > 0.5) airborne = true;
      if (h <= 0 && v < 0) {
        if (airborne) bump = Math.max(bump, -v);
        h = 0; v = 0; airborne = false;
        if (bump > 10) return res('crashed', tick);
      }
    }
    peak = Math.max(peak, v);
    maxAcc = Math.max(maxAcc, Math.abs(a));
    if (tick > o.engageAt + TUNE.meas_ticks + 60) maxAccFly = Math.max(maxAccFly, Math.abs(a));
    if (d <= 0) return res('impact', tick, { vImpact: Math.round(v) });
    if (v < -50 && tick > o.engageAt + 600 && !o.dep) return res('reversing', tick);
    stillSince = Math.abs(v) < 1 && tick > o.engageAt + TUNE.meas_ticks + 600 ? (stillSince ?? tick) : null;
    if (stillSince !== null && tick - stillSince > 3600 && Math.abs(d - standoff) >= Math.max(5, 0.02 * standoff)) return res('held short', tick);
    if (Math.abs(d - standoff) < Math.max(5, 0.02 * standoff) && Math.abs(v) < 1) {
      quietSince ??= tick;
      if (tick - quietSince > 600) return res('arrived', tick, { tArrive: +((quietSince - o.engageAt) / 60).toFixed(0) });
    } else quietSince = null;
  }
  return res('timeout', o.maxTicks);
}

// the user's ship at mass M (kg): 8,279,000 N forward on the mains, 4,374,000 N reverse, 6 SRBs of 950,000 N
const ship = (M, srbMass = 0) => ({ aFwd: 8279e3 / M, aRev: 4374e3 / M, aSrb: 5700e3 / M, massRatio: M / (M - srbMass) });
// with its engines as the user's SHIP RADIOS sheet lists them (2026-10-05), each kind at its own acceleration time:
// forward 2 Small Electric (660,000 N, 0.25 s), 1 Medium Electric (1,300,000, 0.7 s), 2 Small Fuel (2,414,000 at the
// sheet's 0.71 efficiency, 10 s), 1 Medium Fuel (3,905,000, 20 s); reverse the same less the Medium Fuel
const mixedShip = (M, srbMass = 0) => ({
  ...ship(M, srbMass),
  groups: { fwd: [[660e3 / M, 0.25], [1300e3 / M, 0.7], [2414e3 / M, 10], [3905e3 / M, 20]],
    rev: [[660e3 / M, 0.25], [1300e3 / M, 0.7], [2414e3 / M, 10]] },
});

module.exports = { fly, ship, mixedShip };

if (require.main === module) {
  // the generator's diagram (so its TUNE environment variables apply), or a saved circuit
  const d = process.argv[2] ? JSON.parse(require('fs').readFileSync(process.argv[2], 'utf8')) : require('./build_travel_computer.js').diagram;
  const only = process.env.ONLY;
  const cases = [];
  const r = (x) => +x.toFixed(2);
  const add = (name, c) => cases.push([name, c]);
  // The user's trips are 250,000 km or more, and their ship's engines are mostly fuel (mixedShip: 10–20 s to respond).
  // MAX ACCEL 8 m/s² unless said. The target: R 300 km, 9.8 m/s² at the surface unless said. Every case can stop: the
  // reverse thrust holds the ship against the target's pull at the standoff (4,374,000 N ÷ mass: 14.6 m/s² at 300 t,
  // 7.3 at 600 t, 2.2 at 2,000 t). SRBs: 6, 4 t each; they light only where mains and SRBs at full fit under MAX ACCEL.
  const Gm = 1e9;   // 1,000,000 km
  const km = (x) => `${(x / 1e3).toLocaleString('en-US')} km`;
  const weakRev = (c) => ({ ...c, groups: { fwd: c.groups.fwd, rev: c.groups.rev.map(([a, t]) => [0.95 * a, t]) } });
  const moon = { R: 150e3, g0: 1.6 };
  for (const dist of [0.25 * Gm, Gm, 5 * Gm]) add(`300 t, ${km(dist)}`, { ...mixedShip(300e3, 24e3), d: dist });
  add('600 t, 250,000 km, standoff 158 km', { ...mixedShip(600e3, 24e3), d: 0.25 * Gm, lever: 0.7 });
  add('64 t (129 m/s² on the mains), 250,000 km', { ...mixedShip(64e3, 24e3), d: 0.25 * Gm });
  add('2,000 t to a small moon (0.5): SRBs fit, 250,000 km', { ...mixedShip(2000e3, 24e3), d: 0.25 * Gm, R: 100e3, g0: 0.5 });
  add('300 t, MAX ACCEL 50: SRBs fit, 250,000 km', { ...mixedShip(300e3, 24e3), d: 0.25 * Gm, maxAccel: 50 });
  add('64 t, MAX ACCEL 30, 250,000 km', { ...mixedShip(64e3, 24e3), d: 0.25 * Gm, maxAccel: 30 });
  add('falling start 300 t, 2 km over a 9.8 m/s² planet, 250,000 km', { ...mixedShip(300e3, 24e3), d: 0.25 * Gm, dep: { R: 300e3, g0: 9.8, h: 2e3 } });
  add('600 t to a moon (1.6), 250,000 km', { ...mixedShip(600e3, 24e3), d: 0.25 * Gm, ...moon });
  add('300 t to a heavy planet (R 1,200 km, 14), standoff 63 km', { ...mixedShip(300e3, 24e3), d: 0.25 * Gm, R: 1.2e6, g0: 14, lever: 0.6 });
  for (const lever of [0, 1]) add(`300 t, lever ${lever}`, { ...mixedShip(300e3, 24e3), d: 0.25 * Gm, lever });
  add('300 t, already at 20 km/s', { ...mixedShip(300e3, 24e3), d: 0.25 * Gm, v: 20e3 });
  add('300 t, 8 ticks lag', { ...mixedShip(300e3, 24e3), d: 0.25 * Gm, delayTicks: 8 });
  add('300 t, target found after 20 s', { ...mixedShip(300e3, 24e3), d: 0.25 * Gm, blindUntil: 20 });
  add('600 t, reverse 5% under the THRUST RATIO', weakRev({ ...mixedShip(600e3, 24e3), d: 0.25 * Gm, ...moon }));
  add('hovering start 300 t, 2 km over a 9.8 m/s² planet (held there)', { ...mixedShip(300e3, 24e3), d: 0.25 * Gm, dep: { R: 300e3, g0: 9.8, h: 2e3 }, hover: true });
  // all-electric engines (one acceleration time each way)
  add('all-electric 300 t, large electrics (0.95 s)', { ...ship(300e3, 24e3), d: 0.25 * Gm, slewF: 1 / 0.95, slewR: 1 / 0.95 });
  add('all-electric 64 t, small electrics (0.25 s)', { ...ship(64e3, 24e3), d: 0.25 * Gm, slewF: 4, slewR: 4 });
  for (const [name, c] of cases) {
    if (only && !name.includes(only)) continue;
    const t0 = Date.now();
    const res = fly(d, c);
    console.log(`${name.padEnd(48)} ${JSON.stringify(res)} (${Date.now() - t0} ms)`);
  }
}
