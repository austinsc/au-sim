#!/usr/bin/env node
/* Generates an Approximately Up blueprint from a simulator circuit.

     node tools/make_blueprint.js <circuit.json> [--name NAME] [--folder FOLDER] [--out DIR] [--install]
                                  [--jobs N] [--seeds N] [--budget-ms N] [--io bundle|split|free] [--box XxYxZ]
                                  [--flat [--no-floor]] [--seed N] [--steps N] [--no-paint] [--stripes] [--no-sink-stubs]

   Writes <guid>.bp and <guid>.bpmeta to DIR (default blueprints/generated) and prints the report.
   --install also copies the pair into the game's Blueprints folder. Fresh file names only: it never
   overwrites, and the game shows the blueprint in the in-game folder FOLDER (default "au-sim").

   Search: --jobs workers (default: one per CPU, up to 16) try candidate boxes with each I/O mode and --seeds
   seeds (default 4), for up to --budget-ms (default 240000). First they look for any layout, smallest box first
   among boxes with room to spare (4x the parts' volume); then they work down from the best size found, each
   success lowering the bar. The winner has the fewest frame quarters, where a split I/O layout counts 15% more
   and a free one 40% more, so the stubs come out as one group of parallel cables (bundle) unless that costs over
   40% more size. --io fixes the mode and --box the box. --jobs 1 runs bpgen's own sequential search
   instead (--seed picks its seed).

   --flat lays the parts out as one layer on a floor of Frame Quarters: every part upright on the floor, none on top
   of another; cables run on the floor and one level up (over parts, never over a label). Each label lies on the
   floor beside its cable end. The floor holds the parts and labels and anchors the cables lying on it; --no-floor
   leaves it out, for pasting the circuit onto a floor of your own. The box is two cells high (--box XxZ, or XxYxZ
   with Y ignored). Frame quarters count the circuit only; the floor is listed apart.

   Paint: logic parts and internal cables black, input cables and labels green, outputs red; --stripes adds
   accent stripes to the internal cables. */
'use strict';
const fs = require('fs');
const path = require('path');
const os = require('os');
const { Worker, isMainThread, parentPort, workerData } = require('worker_threads');
const { generate, searchBoxes } = require('../bpgen.js');

// ---- worker: run the attempts it is sent ----
if (!isMainThread) {
  parentPort.on('message', (t) => {
    try {
      const out = generate(workerData.circuit, { ...workerData.opts, box: t.box, io: t.io, seed: t.seed, timeBudgetMs: 1e9 });
      parentPort.postMessage({ id: t.id, ok: true, out: { bp: out.bp, meta: out.meta, name: out.name, guid: out.guid, report: out.report, layout: out.layout } });
    } catch (e) {
      parentPort.postMessage({ id: t.id, ok: false, why: (e.attempts || []).map((a) => a.why).join(' | ') || e.message });
    }
  });
  return;
}

const args = process.argv.slice(2);
const flag = (name, def) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : def; };
const has = (name) => args.includes(name);
const file = args.find((a) => !a.startsWith('--') && a.endsWith('.json'));
if (!file) { console.error('usage: node tools/make_blueprint.js <circuit.json> [--name N] [--folder F] [--jobs N] [--out DIR] [--install]'); process.exit(2); }

const circuit = JSON.parse(fs.readFileSync(file, 'utf8'));
const name = flag('--name', path.basename(file, '.json'));
const opts = {
  name, folder: flag('--folder', 'au-sim'),
  steps: flag('--steps') ? Number(flag('--steps')) : undefined,
  paint: !has('--no-paint'), stripes: has('--stripes'), sinkStubs: !has('--no-sink-stubs'),
  flat: has('--flat'), floor: !has('--no-floor'),
};
// --box XxYxZ (or XxZ for a flat layout, whose height bpgen sets)
const boxFlag = () => { const d = flag('--box').split('x').map(Number); return d.length === 2 ? [d[0], 2, d[1]] : d; };
const budget = Number(flag('--budget-ms', 240000));
const jobs = Number(flag('--jobs', Math.max(1, Math.min(os.cpus().length - 1, 16))));
const FACTOR = { bundle: 1, split: 1.15, free: 1.4 };

function sequential() {
  try {
    return Promise.resolve(generate(circuit, { ...opts, seed: Number(flag('--seed', 1)), timeBudgetMs: budget, io: flag('--io'),
      box: flag('--box') ? boxFlag() : undefined }));
  } catch (e) {
    console.error('FAILED:', e.message);
    if (e.attempts) for (const a of e.attempts.slice(-15)) console.error('  ', a.box.join('x'), a.io, a.why);
    process.exit(1);
  }
}

function parallel() {
  const t0 = Date.now();
  const boxes = flag('--box') ? [{ box: boxFlag() }] : searchBoxes(circuit, opts);
  for (const b of boxes) b.cubes = b.box.reduce((n, d) => n * Math.ceil(d / 4), 1);
  const modes = flag('--io') ? [flag('--io')] : ['bundle', 'split', 'free'];
  const seeds = Number(flag('--seeds', 4));
  const roomy = (boxes.partVolume || 0) * 4;
  const tasks = [];
  for (const b of boxes.slice(0, 120)) for (const io of modes) for (let s = 1; s <= seeds; s++) {
    tasks.push({ id: tasks.length, box: b.box, io, seed: s, bound: b.cubes * FACTOR[io], roomy: b.box[0] * b.box[1] * b.box[2] >= roomy });
  }
  // until something works: the smallest roomy box first; after that: the largest bound still under the best
  const pick = () => {
    let k = -1;
    for (let i = 0; i < tasks.length; i++) {
      const t = tasks[i];
      if (t.taken || t.bound >= bestScore) continue;
      if (k < 0) { k = i; continue; }
      const u = tasks[k];
      const better = best
        ? t.bound > u.bound || (t.bound === u.bound && t.seed < u.seed)
        : (t.roomy && !u.roomy) || (t.roomy === u.roomy && (t.bound < u.bound || (t.bound === u.bound && t.seed < u.seed)));
      if (better) k = i;
    }
    if (k >= 0) tasks[k].taken = true;
    return k < 0 ? null : tasks[k];
  };
  let best = null, bestScore = Infinity, running = 0, tried = 0, wins = 0, done = false;
  return new Promise((resolve) => {
    const workers = [];
    const finish = () => {
      if (done) return;
      done = true;
      for (const w of workers) w.terminate();
      console.log(`search: ${tried} attempts in ${((Date.now() - t0) / 1000).toFixed(0)} s on ${workers.length} workers, ${wins} layouts found`);
      if (!best) { console.error('FAILED: no layout found'); process.exit(1); }
      resolve(best);
    };
    const feed = (w) => {
      const late = Date.now() - t0 > budget;
      if (late && best) { finish(); return; }                                     // out of time: keep the best
      const t = late ? null : pick();
      if (!t) { if (!running) finish(); return; }
      running++;
      w.postMessage(t);
    };
    for (let i = 0; i < Math.min(jobs, tasks.length); i++) {
      const w = new Worker(__filename, { workerData: { circuit, opts } });
      w.on('message', (m) => {
        running--; tried++;
        const t = tasks.find((x) => x.id === m.id);
        if (m.ok) {
          wins++;
          const score = m.out.report.frameQuarters * FACTOR[t.io];
          if (score < bestScore) { bestScore = score; best = m.out; }
          console.log(`  ${t.box.join('x')} ${t.io} seed ${t.seed}: ${m.out.report.box.join('x')} = ${m.out.report.frameQuarters} frame quarters${best === m.out ? '  (best so far)' : ''}`);
        }
        if (!done) feed(w);
      });
      w.on('error', (e) => { console.error('worker error:', e.message); running--; });
      workers.push(w);
      feed(w);
    }
  });
}

(jobs > 1 ? parallel() : sequential()).then((out) => {
  out.bp = Uint8Array.from(out.bp);
  const dir = path.resolve(flag('--out', path.join(__dirname, '..', 'blueprints', 'generated')));
  fs.mkdirSync(dir, { recursive: true });
  const write = (d) => {
    const bp = path.join(d, `${out.guid}.bp`), meta = path.join(d, `${out.guid}.bpmeta`);
    if (fs.existsSync(bp) || fs.existsSync(meta)) throw new Error(`refusing to overwrite ${bp}`);
    fs.writeFileSync(bp, out.bp);
    fs.writeFileSync(meta, out.meta);              // UTF-8, no BOM, one line, like the game
    return bp;
  };
  const local = write(dir);
  fs.writeFileSync(path.join(dir, `${out.guid}.layout.json`), JSON.stringify({ report: out.report, layout: out.layout }, null, 1));
  console.log(`wrote ${local}`);
  if (has('--install')) {
    const game = path.join(os.homedir(), 'AppData', 'LocalLow', 'ApproximatelyGames', 'ApproximatelyUp', 'Blueprints');
    if (!fs.existsSync(game)) throw new Error(`no Blueprints folder at ${game}`);
    console.log(`installed ${write(game)}`);
  }
  const r = out.report;
  console.log(`${r.name}: ${r.parts} parts, ${r.cableCells} cable cells, box ${r.box.join('x')} = ${r.frameQuarters} frame quarters, ` +
    `${r.directContacts}/${r.nets} nets by direct contact, ${r.stubs.length} stubs, longest cable ${r.longestCable}, ${r.ms} ms`);
  if (r.flat) console.log(`flat: one layer of parts${r.floor ? ` on a floor of ${r.floor[0]} x ${r.floor[1]} = ${r.floor[0] * r.floor[1]} frame quarters` : ' (no floor: paste it onto one)'}; ${r.raisedCables} cable cells one level up`);
  // a row reads left to right as you face it from outside (+x is to your right on the -z face, to your left on +z)
  console.log(`I/O: ${r.io}` + r.buses.map((b) => `; ${b.face} face, ${b.rows} row(s) (bottom first), left to right from outside: ` +
    (b.face === '-z' ? b.ends : b.ends.slice().reverse()).join(', ')).join(''));
  for (const s of r.stubs) console.log(`  ${s.io === 'in' ? 'IN ' : 'OUT'} ${s.label.padEnd(24)} -> ${s.port.padEnd(28)} label "${s.text || ''}"`);
  if (r.substituted.length) console.log('  substituted:', r.substituted.join(', '));
});
