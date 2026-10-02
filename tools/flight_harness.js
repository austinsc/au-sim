'use strict';
// 1-D approach-to-target flight model for testing autopilot circuits against the engine.
//
//   distance  metres to the target surface (decreases while moving toward it)
//   velocity  m/s toward the target (positive = closing)
//   thrust    the circuit's thruster output, -1..1: + pushes toward the target,
//             - pushes away (a reverse-facing thruster, or the ship flipped)
//
// Accelerometer model is selectable, because the game text only says it
// "measures acceleration in m/s²" (and the wiki: thrust only, free fall reads 0):
//   'signed'    thrust acceleration along the direction of travel (negative while braking)
//   'magnitude' |thrust acceleration|
// The Velocity Meter reads speed (unsigned) unless velocityMeter: 'signed'.
const { CircuitEngine } = require('../engine.js');

function fly(diagram, opts) {
  const o = {
    distance: 100000, velocity: 0, aMax: 20, ratio: 1, gravity: 0, // aMax forward; reverse = aMax / ratio; gravity: m/s² toward the target
    accelerometer: 'signed', velocityMeter: 'speed', maxTicks: 60 * 60 * 30,
    enableAtTick: 0, wiring: {}, // wiring: extra slider values to set (id -> value)
    ...opts,
  };
  const e = new CircuitEngine(diagram);
  const set = (id, value) => { if (e.instances.has(id)) e.instances.get(id).params.value = value; };
  for (const [id, value] of Object.entries(o.wiring)) set(id, value);
  let { distance, velocity } = o;
  let thrustAccel = 0;
  const dt = 1 / 60;
  const log = [];
  for (let tick = 0; tick < o.maxTicks; tick++) {
    // sensors -> circuit inputs (as the game's sensors would read them this tick)
    set('in_distance', Math.max(0, distance));
    set('in_velocity', o.velocityMeter === 'signed' ? velocity : Math.abs(velocity));
    set('in_accel', o.accelerometer === 'magnitude' ? Math.abs(thrustAccel) : thrustAccel * Math.sign(velocity || 1));
    set('in_gravity', -o.gravity); // circuit convention: + helps braking
    set('in_thrust_ratio', o.ratioInput ?? o.ratio);
    set('in_enable', tick >= o.enableAtTick ? 1 : 0);
    e.step();
    const cmd = e.snapshot().thruster_out.out;
    // physics: thrust along the closing direction, plus the target's gravity
    const c = Math.max(-1, Math.min(1, cmd));
    thrustAccel = c >= 0 ? c * o.aMax : c * o.aMax / o.ratio;
    velocity += (thrustAccel + o.gravity) * dt;
    distance -= velocity * dt;
    if (tick % 60 === 0) log.push({ t: tick / 60, distance: Math.round(distance), velocity: +velocity.toFixed(1), cmd });
    if (distance <= 0) return { outcome: 'impact', impactSpeed: +velocity.toFixed(2), t: tick / 60, log };
    if (velocity < -1 && distance > o.distance * 0.01 && tick > 60) {
      // moving away from the target after having been under way
      if (log.length && log[log.length - 1].velocity < -5) return { outcome: 'reversing away', distance: Math.round(distance), velocity: +velocity.toFixed(2), t: tick / 60, log };
    }
    if (tick > o.enableAtTick + 30 && cmd === 0 && Math.abs(velocity) < 1.5) return { outcome: 'stopped', distance: +distance.toFixed(1), velocity: +velocity.toFixed(3), t: +(tick / 60).toFixed(1), log };
  }
  return { outcome: 'timeout', distance: Math.round(distance), velocity: +velocity.toFixed(2), log };
}

module.exports = { fly };

if (require.main === module) {
  const file = process.argv[2] || 'circuits/planet_hop_v2.json';
  const d = require(require('path').resolve(file));
  for (const accelerometer of ['signed', 'magnitude']) {
    for (const [ratio, gravity] of [[1, 0], [2, 0], [1, 5]]) {
      for (const v0 of [0, 300, 1000, 2000]) {
        const r = fly(d, { accelerometer, velocity: v0, ratio, gravity, distance: v0 >= 2000 ? 300000 : 100000 });
        const { log, ...summary } = r;
        console.log(accelerometer.padEnd(9), `ratio=${ratio} g=${gravity} v0=${String(v0).padEnd(4)}`, JSON.stringify(summary));
      }
    }
  }
}
