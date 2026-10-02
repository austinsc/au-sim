'use strict';
// Yaw/pitch attitude model for testing the closed-loop target lock (circuits/raster_sweep_v2.json).
//
//   ship      yaw/pitch angles (deg) and rates (deg/s); the RCS Controller's input c (-1..1) gives an angular
//             acceleration c × alpha (deg/s²) about that axis (optional deadband: |c| below it does nothing)
//   rotometer reads the rate about its axis × the mounting sign (`yawSign`, `pitchSign`)
//   scanner   game rule (SCTick_SpaceScanner): cone = 50 − 49 × input degrees; a body counts once any of its
//             disk is inside the cone (angle to centre − angular radius ≤ cone / 2); it reports the distance of
//             the nearest such body, or 1e20 when the cone is empty
//   targets   [{ yaw, pitch, radius (angular radius, deg), distance }]
//
// lock(diagram, opts) runs: manual phase (joystick still, your cone), then Start, then the circuit flies until
// it is locked, gives up, or time runs out. Result: final pointing error from the chosen target's centre, cone,
// time since Start, and why it stopped.
//   v2 (raster_sweep_v2.json): Start is a Button held for `startTicks`; locked = its `locked` output.
//   v3 (raster_sweep_v3.json, has `in_auto`): the Auto switch is held on from `startAt` (until `stopAt`); the
//      rotometer damping is `damp` (tune_damp_* = −damp × sign); its lever is the cone width (1.02 − scanner
//      input); locked = the 1° cone with the target inside it and the ship turning slower than 0.05 deg/s.
//   Both: held for 60 ticks. `scanDelay` adds ticks of scanner latency; `params` overrides block values.
const { CircuitEngine } = require('../engine.js');

const rad = Math.PI / 180;
const dir = (yaw, pitch) => [Math.cos(pitch * rad) * Math.sin(yaw * rad), Math.sin(pitch * rad), Math.cos(pitch * rad) * Math.cos(yaw * rad)];
const angleBetween = (a, b) => Math.acos(Math.max(-1, Math.min(1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]))) / rad;

function lock(diagram, opts = {}) {
  const o = {
    alpha: 20, deadband: 0, yawSign: 1, pitchSign: 1, circuitYawSign: 1, circuitPitchSign: 1,
    targets: [{ yaw: 8, pitch: -5, radius: 0.3, distance: 2e6 }], target: 0,
    coneManual: 0.4, startAt: 30, startTicks: 10, maxTicks: 60 * 180,
    joystick: () => [0, 0],                 // (tick) -> [yaw, pitch] stick, e.g. to test the abort
    yaw: 0, pitch: 0, yawRate: 0, pitchRate: 0, rateNoise: 0, seed: 1, scanDelay: 0, damp: 0.1, params: {},
    ...opts,
  };
  const e = new CircuitEngine(diagram);
  const set = (id, v) => { e.instances.get(id).params.value = v; };
  const v3 = e.instances.has('in_auto');
  if (v3) {
    if (e.instances.has('tune_damp')) set('tune_damp', -o.damp);   // one D, Auto only (rotometers mounted right)
    else {
      set('tune_damp_yaw', -o.damp * o.circuitYawSign);
      set('tune_damp_pitch', -o.damp * o.circuitPitchSign);
    }
  } else {
    set('tune_yaw_sign', o.circuitYawSign);
    set('tune_rcs', o.rcsSetting ?? o.alpha);
    set('tune_pitch_sign', o.circuitPitchSign);
  }
  for (const [k, v] of Object.entries(o.params)) set(k, v);
  const scans = [];                          // scanner readings waiting out scanDelay
  let { yaw, pitch, yawRate: wy, pitchRate: wp } = o;
  let rnd = o.seed;
  const noise = () => { rnd = (rnd * 1103515245 + 12345) % 2147483648; return (rnd / 2147483648 - 0.5) * 2 * o.rateNoise; };
  let cone = o.coneManual, cmdY = 0, cmdP = 0, lockedFor = 0, everAuto = false;
  const dt = 1 / 60;
  const trace = [];
  for (let tick = 0; tick < o.maxTicks; tick++) {
    // scanner reading for this tick
    const b = dir(yaw, pitch), half = (50 - 49 * Math.max(0, Math.min(1, cone))) / 2;
    let dist = 1e20;
    for (const t of o.targets) {
      if (angleBetween(b, dir(t.yaw, t.pitch)) - t.radius <= half) dist = Math.min(dist, t.distance);
    }
    scans.push(dist);
    if (scans.length > o.scanDelay + 1) scans.shift();
    const [jy, jp] = o.joystick(tick);
    set('in_scan_dist', scans[0]);
    set('in_yaw_rate', wy * o.yawSign + noise());
    set('in_pitch_rate', wp * o.pitchSign + noise());
    set('in_joy_yaw', jy);
    set('in_joy_pitch', jp);
    set('in_cone_manual', v3 ? 1.02 - o.coneManual : o.coneManual);
    if (v3) set('in_auto', tick >= o.startAt && tick < (o.stopAt ?? Infinity) ? 1 : 0);
    else set('in_start', tick >= o.startAt && tick < o.startAt + o.startTicks ? 1 : 0);
    e.step();
    const s = e.snapshot();
    cmdY = s.rcs_yaw.out; cmdP = s.rcs_pitch.out; cone = s.cone_cmd.out;
    const auto = v3 ? (tick >= o.startAt ? 1 : 0) : s.auto.out;
    if (auto) everAuto = true;
    // RCS: angular acceleration about each axis
    const act = (c) => (Math.abs(c) < o.deadband ? 0 : Math.max(-1, Math.min(1, c)) * o.alpha);
    wy += act(cmdY) * dt; wp += act(cmdP) * dt;
    yaw += wy * dt; pitch += wp * dt;
    const tgt = o.targets[o.target];
    const err = angleBetween(dir(yaw, pitch), dir(tgt.yaw, tgt.pitch));
    const coneDeg = 50 - 49 * Math.max(0, Math.min(1, cone));
    if (tick % 30 === 0) trace.push({ t: +(tick / 60).toFixed(1), progress: v3 ? undefined : s.progress.out, cone: +coneDeg.toFixed(2), err: +err.toFixed(3), yaw: +yaw.toFixed(2), pitch: +pitch.toFixed(2) });
    // v3 has no locked output: locked = the 1° cone with the chosen target inside it, and the ship (nearly) still
    const lockedNow = v3 ? (auto && cone >= 0.999 && err - tgt.radius <= 0.5 && Math.hypot(wy, wp) < 0.05) : s.locked.out;
    if (lockedNow) { if (++lockedFor >= 60) return { outcome: 'locked', err: +err.toFixed(3), coneDeg: +coneDeg.toFixed(2), t: +((tick - o.startAt) / 60).toFixed(1), trace }; }
    else lockedFor = 0;
    if (everAuto && !auto && tick > o.startAt + o.startTicks + 5) {
      return { outcome: 'manual', err: +err.toFixed(3), coneDeg: +coneDeg.toFixed(2), t: +(tick / 60).toFixed(1), progress: s.progress?.out, trace };
    }
  }
  const tgt = o.targets[o.target];
  return { outcome: 'timeout', err: +angleBetween(dir(yaw, pitch), dir(tgt.yaw, tgt.pitch)).toFixed(3), trace };
}

module.exports = { lock };

if (require.main === module) {
  const d = require(require('path').resolve(process.argv[2] || 'circuits/raster_sweep_v2.json'));
  const cases = [
    ['one target 8°/−5°, 30° cone', {}],
    ['weak RCS (5 deg/s²)', { alpha: 5 }],
    ['strong RCS (60 deg/s²)', { alpha: 60 }],
    ['big close planet (radius 6°)', { targets: [{ yaw: -10, pitch: 7, radius: 6, distance: 4e5 }] }],
    ['farther body crosses the cone', { targets: [{ yaw: 6, pitch: 4, radius: 0.4, distance: 3e6 }, { yaw: 30, pitch: 2, radius: 1, distance: 9e6 }] }],
    ['nearer body crosses the cone', { targets: [{ yaw: 6, pitch: 4, radius: 0.4, distance: 3e6 }, { yaw: 30, pitch: 2, radius: 1, distance: 9e5 }] }],
    ['RCS 2x stronger than tune_rcs', { alpha: 40, rcsSetting: 20 }],
    ['RCS 2x weaker than tune_rcs', { alpha: 10, rcsSetting: 20 }],
    ['wide 50° cone, far off-centre', { coneManual: 0, targets: [{ yaw: 18, pitch: -12, radius: 0.2, distance: 5e7 }] }],
    ['RCS deadband 0.05', { deadband: 0.05 }],
    ['rate noise ±0.2 deg/s', { rateNoise: 0.2 }],
  ];
  for (const [name, c] of cases) {
    const { trace, ...r } = lock(d, c);
    console.log(name.padEnd(34), JSON.stringify(r));
  }
}
