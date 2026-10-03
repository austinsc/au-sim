'use strict';
// Flip-and-burn flight model for circuits/planet_hop_flip.json (tools/build_planet_hop_flip.js).
//
//   line      d: metres from the ship's centre of mass to the target's surface; v: closing speed (m/s)
//   yaw       psi (deg): 0 = nose at the target, 180 = tail at it; omega (deg/s)
//   engines   THRUST CTL (ch 1) c in 0..1 -> aMax · curve(c) along the nose, after delayTicks, a slew limit (slew per
//             second: the game's SCTick_ValueAccelerator moves a thruster's output toward its input by at most
//             1 / acceleration_time per second, 0.7 s for a Medium Electric) and a first-order lag (tauThrust)
//   attitude  maneuvering thrusters: YAW+ (ch 12) − YAW− (ch 13) -> rcsSign · alpha deg/s² of yaw, PIT+ (14) − PIT− (15)
//             -> rcsSign · alphaP of pitch, each thruster slewing at rodSlew per second (the game's 1 / 0.25 s); the
//             engines push off the centre of mass: epsY and epsP deg/s² of yaw and pitch at full thrust (a 56 t test ship's
//             mass model: -1.73 and -5.75). The turn is sign-free, the holds are not: rcsSign = rotSign is the
//             consistent case, the other is a rotometer mounted the wrong way round
//   sensors   pitch phi (deg) and the yaw error tilt the nose and tail off the line together (hypot)
//             game rules: Space Scanner (ch 30) reads the surface distance of the nearest body any of whose disk is
//             inside its cone (cone = 50 − 49 × SCAN ANGLE), else 1e20; the tail Long Range Distance Meter (ch 38)
//             reads along a line, so only while the tail points into the target's disk, else 1e20; Velocity Meter in
//             Directional mode facing forward (ch 23): v · cos(nose angle), smoothed out += (new − out) · 0.1535 a
//             tick (SCTick_VelocityMeter); the Accelerometer the magnitude of the ship's acceleration, gravity
//             included, smoothed by 0.08 a tick (SCTick_Accelerometer); the Gravitymeter g; the yaw rotometer
//             rotSign · omega
//   target    radius R, surface gravity g0 (g = g0 (R / (R + d))²); scannerAhead/rearAft: sensor offsets (m)
//   aimOff    the nose's error off the target's centre at the flip (deg): the tail then misses by as much
//
// fly(diagram, opts) -> { outcome: 'stopped' | 'holding' | 'impact' | 'reversing' | 'timeout', ... }
//   stopped/holding: speed under vStop for holdCheck s after the flip; tail = tail height above the surface,
//   holdV = the largest speed while holding, thr = throttle at the end
const { CircuitEngine } = require('../engine.js');

const rad = Math.PI / 180;
function fly(diagram, opts = {}) {
  const o = {
    d: 500000, v: 0, aMax: 100, curve: (c) => c, tauThrust: 0.2, delayTicks: 2, slew: Infinity, alpha: 8, rcsSign: 1, rotSign: 1,
    alphaP: 24, epsY: 0, epsP: 0, rodSlew: 4, phi0: 0, maxPhi: 0,
    damping: 0, R: 200000, g0: 9.8, scannerAhead: 13, rearAft: 9, psi0: 0, omega0: 0, scan: undefined, aimOff: 0,
    maxTicks: 60 * 60 * 60, engageAt: 30, vStop: 1, holdCheck: 20, ...opts,
  };
  // the rest of the ship on the radio: a slider and a transmitter for each sensor node the computer listens to,
  // and a receiver on each channel it sends
  const d2 = JSON.parse(JSON.stringify(diagram));
  const ext = {};
  for (const [ch, name] of [[30, 'fwd'], [38, 'rear'], [23, 'vz']]) {
    const s = `ext_${name}`, t = `ext_${name}_tx`;
    d2.instances.push({ id: s, type_id: 'slider', parameters: { value: 0 }, position: { x: 0, y: 0 } });
    d2.instances.push({ id: t, type_id: 'wireless_transmitter', parameters: { channel: ch }, position: { x: 0, y: 0 } });
    d2.edges.push({ from_instance: s, from_port: 'out', to_instance: t, to_port: 'tx' });
    ext[name] = { s, t, ch };
  }
  for (const [ch, id] of [[1, 'lis_thrust'], [12, 'lis_yaw_pos'], [13, 'lis_yaw_neg'], [14, 'lis_pit_pos'], [15, 'lis_pit_neg']]) {
    d2.instances.push({ id, type_id: 'wireless_transmitter', parameters: { channel: ch }, position: { x: 0, y: 0 } });
  }
  return flyEngine(new CircuitEngine(d2), o, ext);
}

function flyEngine(e, o, ext) {
  const inst = (id) => e.instances.get(id);
  const setVal = (id, v) => { inst(id).params.value = v; };
  const setOut = (id, port, v) => { inst(id).params[port] = v; };
  if (o.scan !== undefined) inst('knob_scan').params.out = o.scan;
  let { d, v, psi0: psi, omega0: omega } = o;
  let aT = 0, accSmooth = 0, vzOut = v, flipStart = null, flipTime = null, peak = 0, minD = d, cOut = 0;
  let phi = o.phi0, q = 0, maxPhi = 0;
  const rods = { yp: 0, yn: 0, pp: 0, pn: 0 };
  const slewTo = (k, want) => { rods[k] += Math.max(-o.rodSlew / 60, Math.min(o.rodSlew / 60, Math.max(0, Math.min(1, want)) - rods[k])); return rods[k]; };
  let quietSince = null, holdV = 0, c = 0;
  const cmdQ = [];
  const dt = 1 / 60;
  const scanCone = () => 50 - 49 * Math.max(0, Math.min(1, inst('knob_scan').params.out));
  const res = (outcome, tick, extra = {}) => ({
    outcome, d: Math.round(d), tail: Math.round(d - o.rearAft), v: +v.toFixed(2), t: +(tick / 60).toFixed(1),
    flipStart: flipStart === null ? null : +(flipStart / 60).toFixed(1), flipTime: flipTime && +flipTime.toFixed(1),
    peak: Math.round(peak), minTail: Math.round(minD - o.rearAft), thr: +c.toFixed(3), maxPhi: +maxPhi.toFixed(2), ...extra,
  });
  for (let tick = 0; tick < o.maxTicks; tick++) {
    // sensors, as the game would read them this tick
    const g = o.g0 * (o.R / (o.R + Math.max(0, d))) ** 2;
    const rho = Math.asin(o.R / (o.R + Math.max(1, d))) / rad;                   // target's angular radius
    const noseOff = Math.abs(((psi % 360) + 540) % 360 - 180);                      // nose angle off the line
    const noseAim = Math.hypot(flipStart === null ? noseOff : Math.abs(noseOff - o.aimOff), phi);   // ...off the target's centre
    const tailAim = Math.hypot(Math.abs(180 - noseOff - o.aimOff), phi);                             // tail angle off the centre
    setVal(ext.fwd.s, noseAim - rho <= scanCone() / 2 ? Math.max(0, d - o.scannerAhead) : 1e20);
    setVal(ext.rear.s, tailAim <= rho ? Math.max(0, d - o.rearAft) : 1e20);
    vzOut += (v * Math.cos(noseOff * rad) - vzOut) * 0.1535;
    setVal(ext.vz.s, vzOut);
    // ship acceleration: thrust along the nose (closing component aT·cos(noseOff)) plus gravity toward the target
    const ax = aT * Math.cos(noseOff * rad) + g, ay = aT * Math.sin(noseOff * rad);
    accSmooth += (Math.hypot(ax, ay) - accSmooth) * 0.08;
    setOut('accel', 'acceleration', accSmooth);
    setOut('grav', 'gravity', g);
    setOut('yaw_rate', 'angular_velocity', o.rotSign * omega);
    setOut('pitch_rate', 'angular_velocity', o.rotSign * q);
    setOut('sw_auto', 'out', tick >= o.engageAt ? 1 : 0);
    e.step();
    const snap = e.snapshot();
    const rx = (id) => snap[id].rx ?? 0;
    cmdQ.push(Math.max(0, Math.min(1, rx('lis_thrust'))));
    c = cmdQ.length > o.delayTicks ? cmdQ.shift() : 0;
    const u = slewTo('yp', rx('lis_yaw_pos')) - slewTo('yn', rx('lis_yaw_neg'));
    const up = slewTo('pp', rx('lis_pit_pos')) - slewTo('pn', rx('lis_pit_neg'));
    // physics
    if (flipStart === null && snap.notc.out < 0.5) flipStart = tick;
    if (flipStart !== null && flipTime === null && 180 - noseOff < 2 && Math.abs(omega) < 2) flipTime = (tick - flipStart) / 60;
    cOut += Math.max(-o.slew * dt, Math.min(o.slew * dt, c - cOut));
    aT += (o.aMax * o.curve(cOut) - aT) * Math.min(1, dt / o.tauThrust);
    omega += (o.rcsSign * o.alpha * u + o.epsY * aT / o.aMax - o.damping * omega) * dt;
    psi += omega * dt;
    q += (o.rcsSign * o.alphaP * up + o.epsP * aT / o.aMax) * dt;
    phi += q * dt;
    maxPhi = Math.max(maxPhi, Math.abs(phi));
    v += (aT * Math.cos(noseOff * rad) * Math.cos(phi * rad) + g) * dt;
    if (Math.abs(phi) > 60) return res('tumble', tick, { phi: Math.round(phi) });
    d -= v * dt;
    peak = Math.max(peak, v);
    minD = Math.min(minD, d);
    if (d <= o.rearAft) return res('impact', tick);
    if (v < -150) return res("reversing", tick);
    if (flipTime !== null) {
      if (Math.abs(v) < o.vStop) quietSince ??= tick;
      if (quietSince !== null) {
        holdV = Math.max(holdV, Math.abs(v));
        if (holdV > 20) { quietSince = null; holdV = 0; }
        else if (tick - quietSince > o.holdCheck * 60) return res(g >= 0.5 ? 'holding' : 'stopped', tick, { holdV: +holdV.toFixed(2) });
      }
    }
  }
  return res('timeout', o.maxTicks);
}

module.exports = { fly };

if (require.main === module) {
  const file = process.argv[2] || require('path').join(__dirname, '..', 'circuits', 'planet_hop_flip.json');
  const d = JSON.parse(require('fs').readFileSync(file, 'utf8'));
  const only = process.env.ONLY;
  const rows = [];
  const cases = [];
  for (const alpha of [6, 10, 16]) for (const [rcsSign, rotSign] of [[1, 1], [-1, 1], [1, -1]]) {
    for (const [dist, aMax, g0] of [[50e3, 100, 0], [500e3, 175, 9.8], [5e6, 220, 9.8], [500e3, 40, 3], [2e6, 175, 1.6]]) {
      cases.push({ d: dist, aMax, g0, alpha, rcsSign, rotSign });
    }
  }
  for (const tau of [0.05, 0.5]) cases.push({ d: 500e3, aMax: 175, g0: 9.8, alpha: 10, tauThrust: tau, delayTicks: 6 });
  for (const aimOff of [2, 8]) cases.push({ d: 2e6, aMax: 175, g0: 9.8, alpha: 10, aimOff });
  cases.push({ d: 500e3, v: 3000, aMax: 175, g0: 9.8, alpha: 10 });                  // already moving at enable
  cases.push({ d: 20e3, aMax: 175, g0: 9.8, alpha: 10 });                            // short hop
  // a 56 t test ship: electric mains only (fuel engines take 10-20 s to spool), Medium Electric slew 1/0.7 per s,
  // the mass model's thrust offsets (and twice them), both consistent sign conventions
  for (const [dist, g0] of [[50e3, 0], [500e3, 9.8], [5e6, 9.8], [2e6, 1.6], [20e3, 9.8]]) for (const [alpha, k, sg] of [[18.4, 1, 1], [18.4, 2, 1], [18.4, 1, -1], [9, 2, 1]]) {
    cases.push({ d: dist, aMax: 69, g0, alpha, alphaP: alpha * 24 / 18.4, epsY: -1.73 * k, epsP: -5.75 * k, rcsSign: sg, rotSign: sg,
      slew: 1 / 0.7, tauThrust: 0.05, delayTicks: 4, ship: 1 });
  }
  for (const c of cases) {
    const r = fly(d, c);
    delete c.ship;
    const k = Object.entries(c).map(([a, b]) => `${a} ${b}`).join(', ');
    if (!only || k.includes(only)) rows.push(`${k.padEnd(70)} ${JSON.stringify(r)}`);
  }
  console.log(rows.join('\n'));
}
