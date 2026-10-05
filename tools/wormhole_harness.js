'use strict';
// Black hole flight model for circuits/wormhole_nav.json (tools/build_wormhole_nav.js).
//
//   line      r: metres from the black hole's centre along the tunnel axis; v: closing speed (m/s, + inward)
//   gravity   the game's (UniverseGravitySystem): 1000 · (600 km / r)² m/s², 1000 inside 600 km; on the open tunnel's
//             axis it blends toward min(g / 2, 200) from 4 radii in (fully at 1 radius and inside)
//   yaw       psi (deg): 0 = nose at the hole, 180 = tail at it; omega (deg/s)
//   engines   THRUST CTL (ch 1) c in 0..1 -> aMax · c along the nose, after delayTicks, a slew limit (1 / acceleration
//             time per second, 0.7 s for a Medium Electric) and a first-order lag (tauThrust)
//   attitude  YAW+ (12) − YAW− (13) -> rcsSign · alpha deg/s² of yaw, PIT+ (14) − PIT− (15) -> rcsSign · alphaP of pitch,
//             each thruster slewing at rodSlew per second; the engines push off the centre of mass: epsY, epsP deg/s² at
//             full thrust. While the engines fire, their gimbals' angular stabilization drags the spin toward the
//             maneuvering thrusters' own target at up to `pull` deg/s² (the game's SpaceshipPartsApplyForces)
//   sensors   Gravitymeter g (instant); Velocity Meter, Directional, facing forward (ch 23): v · cos(nose angle),
//             smoothed out += (new − out) · 0.1535 a tick; Accelerometer: the magnitude of the ship's acceleration,
//             gravity included, smoothed by 0.08 a tick; the rotometers rotSign · omega, rotSign · q
//   strain    per tick, the net linear acceleration (thrust + gravity), and for a part L metres from the centre of mass
//             the spin's (|dω/dt| + ω²) · L on top. The game's rule: a part whose velocity changes more than 0.173 m/s
//             in a tick (10.39 m/s²) takes 0.22 · mass · Δv² of strain; ironKg = the heaviest part an Iron joint (1600)
//             holds at the worst tick, with the shock pointing straight at it
//
// fly(diagram, opts) -> { outcome, ... }
//   holding  (Descend off) speed under 1 m/s for holdCheck s after the flip; rHold km, gHold, thr
//   tunnel   (Descend on) reached rEnd (default 1 radius): vEnd, and the strain figures on the way
//   fell / reversing / tumble / timeout: failures
const { CircuitEngine } = require('../engine.js');

const rad = Math.PI / 180, R = 600e3, G0 = 1000, ATHR = 10.39;
function gravity(r, tunnel = true) {
  let g = G0 * Math.min(1, (R / Math.max(r, 1)) ** 2);
  const z = r / R;
  if (tunnel && z < 4) {
    const capped = Math.min(g / 2, 200);
    g = z < 1 ? capped : g + (capped - g) * Math.min(1, Math.max(0, (4 - z) / 3));
  }
  return g;
}

function fly(diagram, opts = {}) {
  const o = {
    r: 15000e3, v: 0, aMax: 5, tauThrust: 0.05, delayTicks: 4, slew: 1 / 0.7, alpha: 3, rcsSign: 1, rotSign: 1,
    alphaP: 3, epsY: 0, epsP: 0, rodSlew: 4, pull: 0, psi0: 0, omega0: 0, L: 25, tunnel: true,
    descendAt: null, descendFor: Infinity, rEnd: R, maxTicks: 60 * 3600 * 8, engageAt: 30, holdCheck: 60, ...opts,
  };
  const d2 = JSON.parse(JSON.stringify(diagram));
  d2.instances.push({ id: 'ext_vz', type_id: 'slider', parameters: { value: 0 }, position: { x: 0, y: 0 } });
  d2.instances.push({ id: 'ext_vz_tx', type_id: 'wireless_transmitter', parameters: { channel: 23 }, position: { x: 0, y: 0 } });
  d2.edges.push({ from_instance: 'ext_vz', from_port: 'out', to_instance: 'ext_vz_tx', to_port: 'tx' });
  for (const [ch, id] of [[1, 'lis_thrust'], [12, 'lis_yaw_pos'], [13, 'lis_yaw_neg'], [14, 'lis_pit_pos'], [15, 'lis_pit_neg']]) {
    d2.instances.push({ id, type_id: 'wireless_transmitter', parameters: { channel: ch }, position: { x: 0, y: 0 } });
  }
  const e = new CircuitEngine(d2);
  const inst = (id) => e.instances.get(id);
  let { r, v, psi0: psi, omega0: omega } = o;
  let aT = 0, accSmooth = 0, vzOut = v, cOut = 0, c = 0, phi = 0, q = 0, maxPhi = 0;
  let flipStart = null, flipDone = null, quietSince = null, holdAt = null, descendTick = null;
  let maxLin = 0, maxPart = 0, strainTicks = 0, maxLinApproach = 0, peak = 0, minR = r;
  const rods = { yp: 0, yn: 0, pp: 0, pn: 0 };
  const slewTo = (k, want) => { rods[k] += Math.max(-o.rodSlew / 60, Math.min(o.rodSlew / 60, Math.max(0, Math.min(1, want)) - rods[k])); return rods[k]; };
  const cmdQ = [];
  const dt = 1 / 60;
  const res = (outcome, tick, extra = {}) => ({
    outcome, rKm: +(r / 1e3).toFixed(1), v: +v.toFixed(1), t: +(tick / 60).toFixed(0),
    flipAt: flipStart === null ? null : +(flipStart / 60).toFixed(0), flipS: flipDone && +((flipDone - flipStart) / 60).toFixed(1),
    peakV: Math.round(peak), maxLinApproach: +maxLinApproach.toFixed(2), maxLin: +maxLin.toFixed(1), maxPart: +maxPart.toFixed(1),
    strainS: +(strainTicks / 60).toFixed(0), ironKg: maxPart > ATHR ? Math.round(1600 / (0.22 * (maxPart / 60) ** 2)) : null,
    maxPhi: +maxPhi.toFixed(2), thr: +c.toFixed(3), ...extra,
  });
  for (let tick = 0; tick < o.maxTicks; tick++) {
    const g = gravity(r, o.tunnel);
    const noseOff = Math.abs(((psi % 360) + 540) % 360 - 180);
    vzOut += (v * Math.cos(noseOff * rad) - vzOut) * 0.1535;
    inst('ext_vz').params.value = vzOut;
    const ax = aT * Math.cos(noseOff * rad) * Math.cos(phi * rad) + g, ay = aT * Math.sin(noseOff * rad);
    const aLin = Math.hypot(ax, ay);
    accSmooth += (aLin - accSmooth) * 0.08;
    inst('accelerometer').params.acceleration = accSmooth;
    inst('gravitymeter').params.gravity = g;
    inst('yaw_rate').params.angular_velocity = o.rotSign * omega;
    inst('pitch_rate').params.angular_velocity = o.rotSign * q;
    inst('autopilot').params.out = tick >= o.engageAt ? 1 : 0;
    let desc = o.descendAt === 'hold' ? holdAt !== null && tick >= holdAt + 30 * 60 : o.descendAt !== null && tick >= o.descendAt;
    if (desc && descendTick === null) descendTick = tick;
    if (descendTick !== null && tick - descendTick > o.descendFor * 60) desc = false;   // Descend off again: abort
    inst('descend').params.out = desc ? 1 : 0;
    e.step();
    const snap = e.snapshot();
    const rx = (id) => snap[id].rx ?? 0;
    cmdQ.push(Math.max(0, Math.min(1, rx('lis_thrust'))));
    c = cmdQ.length > o.delayTicks ? cmdQ.shift() : 0;
    const u = slewTo('yp', rx('lis_yaw_pos')) - slewTo('yn', rx('lis_yaw_neg'));
    const up = slewTo('pp', rx('lis_pit_pos')) - slewTo('pn', rx('lis_pit_neg'));
    if (flipStart === null && snap.flipped.out > 0.5) flipStart = tick;
    if (flipStart !== null && flipDone === null && 180 - noseOff < 2 && Math.abs(omega) < 2) flipDone = tick;
    // physics
    cOut += Math.max(-o.slew * dt, Math.min(o.slew * dt, c - cOut));
    aT += (o.aMax * cOut - aT) * Math.min(1, dt / o.tauThrust);
    const om0 = omega, q0 = q;
    omega += (o.rcsSign * o.alpha * u + o.epsY * aT / o.aMax) * dt;
    q += (o.rcsSign * o.alphaP * up + o.epsP * aT / o.aMax) * dt;
    if (o.pull > 0 && aT > 0.01 * o.aMax) {                       // gimbal drag while the engines fire
      const step = o.pull * (aT / o.aMax) * dt;
      const ty = o.rcsSign * o.alpha * u, tp = o.rcsSign * o.alphaP * up;
      omega = Math.abs(ty - omega) <= step ? ty : omega + Math.sign(ty - omega) * step;
      q = Math.abs(tp - q) <= step ? tp : q + Math.sign(tp - q) * step;
    }
    psi += omega * dt;
    phi += q * dt;
    maxPhi = Math.max(maxPhi, Math.abs(phi));
    v += ax * dt;
    r -= v * dt;
    // strain: net linear acceleration, plus the spin's at L metres
    const dw = Math.hypot(omega - om0, q - q0) * rad * 60, w2 = (omega * rad) ** 2 + (q * rad) ** 2;
    const aPart = aLin + (dw + w2) * o.L;
    maxLin = Math.max(maxLin, aLin);
    maxPart = Math.max(maxPart, aPart);
    if (descendTick === null) maxLinApproach = Math.max(maxLinApproach, aPart);
    if (aPart > ATHR) strainTicks++;
    peak = Math.max(peak, v);
    minR = Math.min(minR, r);
    if (Math.abs(phi) > 60) return res('tumble', tick, { phi: Math.round(phi) });
    if (v < -300) return res('reversing', tick);
    if (r <= o.rEnd) return res(descendTick !== null ? 'tunnel' : 'fell', tick, { vEnd: Math.round(v) });
    if (flipDone !== null && (descendTick === null || tick - descendTick > o.descendFor * 60)) {
      if (Math.abs(v) < 1) quietSince ??= tick; else quietSince = null;
      if (quietSince !== null && tick - quietSince > o.holdCheck * 60) {
        const held = res('holding', tick, { rHold: +(r / 1e3).toFixed(0), gHold: +g.toFixed(2) });
        if (descendTick !== null) return { ...held, outcome: 'held again' };   // Descend went off: it stopped
        if (o.descendAt !== 'hold') return held;
        holdAt ??= tick;
      }
    }
  }
  return res('timeout', o.maxTicks);
}

module.exports = { fly, gravity };

if (require.main === module) {
  const file = process.argv[2] || require('path').join(__dirname, '..', 'circuits', 'wormhole_nav.json');
  const d = JSON.parse(require('fs').readFileSync(file, 'utf8'));
  const only = process.env.ONLY;
  const cases = [];
  for (const aMax of [1.5, 3, 6, 12, 25]) for (const r of [8000e3, 15000e3, 40000e3]) cases.push({ aMax, r });
  for (const alpha of [0.5, 1.5, 6]) cases.push({ aMax: 6, r: 15000e3, alpha, alphaP: alpha });
  for (const [rcsSign, rotSign] of [[-1, -1], [-1, 1], [1, -1]]) cases.push({ aMax: 6, r: 15000e3, rcsSign, rotSign });
  cases.push({ aMax: 6, r: 15000e3, v: 1500 });                                  // already falling in at 1.5 km/s
  cases.push({ aMax: 6, r: 15000e3, epsY: -0.3, epsP: -1 });                     // engines off the centre of mass
  cases.push({ aMax: 6, r: 15000e3, pull: 6 });                                   // gimbal drag on the holds
  cases.push({ aMax: 6, r: 15000e3, slew: 1 / 0.25, delayTicks: 8 });
  for (const aMax of [1.5, 6, 25]) cases.push({ aMax, r: 15000e3, descendAt: 'hold' });
  for (const aMax of [1.5, 6, 25]) cases.push({ aMax, r: 15000e3, descendAt: 0 });
  for (const [aMax, s] of [[6, 300], [25, 400]]) cases.push({ aMax, r: 15000e3, descendAt: 'hold', descendFor: s });   // abort
  for (const c of cases) {
    if (only && !JSON.stringify(c).includes(only)) continue;
    const t0 = Date.now();
    const r = fly(d, c);
    const k = Object.entries(c).map(([a, b]) => `${a} ${b}`).join(', ');
    console.log(`${k.padEnd(52)} ${JSON.stringify(r)} (${Date.now() - t0} ms)`);
  }
}
