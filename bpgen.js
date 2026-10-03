/* =========================================================================
   Approximately Up — blueprint generator (bpgen.js)

   generate(circuit, opts) -> { bp: Uint8Array, meta: string, name, guid, report, layout }

   Turns a simulator circuit (aupbuilder JSON: instances + edges) into a game blueprint.
   Phase 1 places the logic parts listed in bpdata.js (built by tools/bp/build_bpdata.py).
   Every connection to any other part (sliders, toggles, sensors, actuators...) becomes a cable
   stub that runs to the blueprint's outer face: inputs leave through the -z face, outputs
   through the +z face.

   Method: simulated-annealing placement on a cell grid (fewest 4x4x4 frame-quarter cubes
   first, then shortest wiring, direct port contact where possible, every part touching
   another), then negotiated-congestion routing (PathFinder) of the remaining nets, then an
   independent check that re-derives every connection from the cells using the game's
   open-face rule. Formats and rules: tools/bp/NOTES.md.
   ========================================================================= */
'use strict';
(function (root) {
const D = (typeof BP_DATA !== 'undefined') ? BP_DATA : require('./bpdata.js');

// ---------- paint (SpaceshipComponentColor; 0 = unpainted) ----------
const PAINT = { none: 0, white: 1, black: 2, darkgray: 3, gray: 4, lightgray: 5, yellow: 6, orange: 7, purple: 8,
  pink: 9, red: 10, teal: 11, green: 12, blue: 13, brown: 14, cyan: 15, terracotta: 16, burgundy: 17, celadon: 18,
  moss: 19, petrol: 20, periwinkle: 21, violet: 22, iron: 200, nano: 201 };
// Logic parts and internal cables are black; only the circuit's inputs and outputs (their cables and labels) are
// colour-coded, so they stand out.
const PART_COLOR = 'black';
const CABLE_PAINT = { net: 'black', in: 'green', out: 'red' };
// opts.stripes = true stripes each internal cable: alternate cells take a per-cable accent (off by default).
const NET_ACCENTS = ['yellow', 'cyan', 'orange', 'violet', 'teal', 'pink', 'blue', 'terracotta', 'celadon', 'purple',
  'periwinkle', 'moss', 'burgundy', 'petrol', 'brown', 'white', 'lightgray'];

// ---------- vectors and orientations ----------
const DIRS = [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]];
const vadd = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const vsub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const veq = (a, b) => a[0] === b[0] && a[1] === b[1] && a[2] === b[2];
const dirIndex = (v) => DIRS.findIndex((d) => veq(d, v));
const opposite = (i) => i ^ 1;
const ORI = {};
for (const [k, m] of Object.entries(D.orientations)) ORI[+k] = m;
const rot = (m, q) => [
  m[0][0] * q[0] + m[0][1] * q[1] + m[0][2] * q[2],
  m[1][0] * q[0] + m[1][1] * q[1] + m[1][2] * q[2],
  m[2][0] * q[0] + m[2][1] * q[1] + m[2][2] * q[2]];
const KS = Object.keys(ORI).map(Number);
const frontOf = (k) => rot(ORI[k], [0, 0, 1]);
const upOf = (k) => rot(ORI[k], [0, 1, 0]);
const UPRIGHT = {};                              // front direction index -> code with local +y = world +y
for (const k of KS) if (veq(upOf(k), [0, 1, 0])) UPRIGHT[dirIndex(frontOf(k))] = k;
const LYING = {};                                // reading direction index -> code of a label lying face up
for (const k of KS) if (veq(frontOf(k), [0, 1, 0])) LYING[dirIndex(rot(ORI[k], [-1, 0, 0]))] = k;
const CORNER = {};                               // (open a, open b) -> code with local +y -> a, local +z -> b
for (const k of KS) CORNER[dirIndex(upOf(k)) * 6 + dirIndex(frontOf(k))] = k;
const STRAIGHT = [0, 0, 9, 9, 16, 16];           // codes the game itself uses for x, y and z runs
for (let i = 0; i < 6; i += 2) {
  const f = frontOf(STRAIGHT[i]);
  if (Math.abs(f[i >> 1]) !== 1) throw new Error('straight-cable orientation table mismatch');
}

// ---------- part geometry ----------
const geoCache = new Map();
// Where a part's joint areas are, when they do not cover every face: (local cell, outward normal) -> whether that
// cell face holds. The Wireless Transmitter's prefab JointsArea list covers its bottom and the lower row of its four
// sides; its top and upper row hold nothing. Every other logic part is one cell tall with a joint on each face.
const JOINT_AT = { wireless_transmitter: (c, n) => n[1] === -1 || (n[1] === 0 && c[1] === 0) };

function geometry(type, k, mir) {
  const key = `${type}|${k}|${mir ? 1 : 0}`;
  let g = geoCache.get(key);
  if (g) return g;
  const P = D.parts[type];
  const [w, h, d] = P.size;
  const m = ORI[k];
  const local = [];
  for (let x = 0; x < w; x++) for (let y = 0; y < h; y++) for (let z = 0; z < d; z++) local.push([x, y, z]);
  const rl = local.map((c) => rot(m, c));
  const mn = [0, 1, 2].map((a) => Math.min(...rl.map((c) => c[a])));
  const cells = rl.map((c) => vsub(c, mn));
  const dims = [0, 1, 2].map((a) => Math.max(...cells.map((c) => c[a])) + 1);
  const ports = {};
  const clamp = (v, hi) => Math.max(0, Math.min(hi, v));
  for (const [name, p] of Object.entries(P.ports)) {
    let [x, y, z] = p.cell;
    if (mir) x = w - 1 - x;
    const face = [clamp(x, w - 1), clamp(y, h - 1), clamp(z, d - 1)];
    const cell = vsub(rot(m, [x, y, z]), mn), fc = vsub(rot(m, face), mn);
    ports[name] = { name, cell, face: fc, inward: dirIndex(vsub(fc, cell)), dir: p.dir, kind: p.kind || 'data' };
  }
  // cells just outside the footprint (for contact / support checks), and those across a joint area
  const inside = new Set(local.map((c) => c.join()));
  const shellSet = new Map(), jointSet = new Map();
  const holds = JOINT_AT[type];
  for (const c of local) for (const dd of DIRS) {
    const nl = vadd(c, dd);
    if (inside.has(nl.join())) continue;
    const n = vsub(rot(m, nl), mn);
    shellSet.set(n.join(), n);
    if (!holds || holds(c, dd)) jointSet.set(n.join(), n);
  }
  g = { cells, dims, ports, shell: [...shellSet.values()], jointShell: [...jointSet.values()], portList: Object.values(ports) };
  geoCache.set(key, g);
  return g;
}

function variantsFor(type, all = true) {
  // every orientation the game allows (all 24 occur in saved blueprints), normal or mirrored twin;
  // upright ones (local +y = world +y) are marked so the placer can prefer them
  // (a part flagged upright_only, e.g. an Axis Rotometer that must measure yaw, only ever stands upright)
  const out = [];
  const twins = !!D.parts[type].mirrored_hash;
  const ks = all && !D.parts[type].upright_only ? KS : [4, 5, 0, 1].map((f) => UPRIGHT[f]);
  for (const k of ks) {
    const upright = veq(upOf(k), [0, 1, 0]);
    out.push({ k, mir: false, upright });
    if (twins) out.push({ k, mir: true, upright });
  }
  return out;
}

// ---------- the circuit's nets ----------
function netlist(circuit, opts = {}) {
  const included = circuit.instances.filter((i) => D.parts[i.type_id]);
  const inc = new Set(included.map((i) => i.id));
  const byId = new Map(circuit.instances.map((i) => [i.id, i]));
  const nets = [], stubs = [], usedOut = new Set(), skipped = [];
  for (const e of circuit.edges) {
    const a = inc.has(e.from_instance), b = inc.has(e.to_instance);
    if (a) usedOut.add(`${e.from_instance}.${e.from_port}`);
    if (a && b) nets.push({ a: { id: e.from_instance, port: e.from_port }, b: { id: e.to_instance, port: e.to_port } });
    else if (b) stubs.push({ end: { id: e.to_instance, port: e.to_port }, io: 'in', label: e.from_instance,
      from: byId.get(e.from_instance)?.type_id });
    else if (a) stubs.push({ end: { id: e.from_instance, port: e.from_port }, io: 'out', label: e.to_instance,
      to: byId.get(e.to_instance)?.type_id });
    else skipped.push(e);
  }
  // a part none of whose outputs feeds anything is a circuit output: stub every output it has
  for (const i of (opts.sinkStubs === false ? [] : included)) {
    const outs = Object.entries(D.parts[i.type_id].ports).filter(([, p]) => p.dir === 'out').map(([n]) => n);
    if (outs.length && outs.every((o) => !usedOut.has(`${i.id}.${o}`))) {
      for (const o of outs) stubs.push({ end: { id: i.id, port: o }, io: 'out', label: outs.length > 1 ? `${i.id}.${o}` : i.id });
    }
  }
  const substituted = circuit.instances.filter((i) => !inc.has(i.id)).map((i) => `${i.id} (${i.type_id})`);
  return { included, nets, stubs, substituted, skipped };
}

// ---------- seeded random ----------
function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---------- placement ----------
const BIG = 1000;
const MAX_NET = 21, MAX_STUB = 11;
const NET_OVERHEAD = 2;                          // extra cost per cabled net, so direct contact is preferred

class Layout {
  // opts.flat: one layer on a floor (see generate). Every part stands upright on the floor (y = 0), none on another;
  // cables run on the floor and one level up, over the parts too, but never over a label. The floor holds the parts
  // and the labels, which lie on it, so they need not hold each other. opts.floor: the floor is in the blueprint.
  // opts.maxNet / opts.maxStub: cable reach (a floor anchors the straight cells lying on it).
  constructor(parts, nets, stubs, box, buses = [], opts = {}) {
    this.parts = parts;                           // [{id, type, vars, v, o}]
    this.nets = nets; this.stubs = stubs;         // stubs carry face ('-z' / '+z') and, on a bus, its index
    this.box = box;
    this.flat = !!opts.flat; this.floor = !!opts.floor;
    this.maxNet = opts.maxNet || MAX_NET; this.maxStub = opts.maxStub || MAX_STUB;
    const [X, Y, Z] = box;
    this.grid = new Int16Array(X * Y * Z).fill(-1);
    this.portOwner = new Int32Array(X * Y * Z).fill(-1);
    // I/O buses: the bus cable cells (each end cell and the goal cell just inside it) belong to their stub and
    // stay free of parts
    this.buses = buses;
    this.tailOwner = new Int32Array(X * Y * Z).fill(-1);
    this.tailKind = new Uint8Array(X * Y * Z);     // 1 = end cell (fixed straight cable), 2 = goal cell
    this.index = new Map(parts.map((p, i) => [p.id, i]));
    // port -> role: { net: n } or { stub: s }
    this.role = parts.map(() => ({}));
    nets.forEach((n, ni) => {
      this.role[this.index.get(n.a.id)][n.a.port] = { net: ni };
      this.role[this.index.get(n.b.id)][n.b.port] = { net: ni };
    });
    stubs.forEach((s, si) => { this.role[this.index.get(s.end.id)][s.end.port] = { stub: si }; });
    this.netEnds = nets.map((n) => [this.index.get(n.a.id), n.a.port, this.index.get(n.b.id), n.b.port]);
    this.stubEnds = stubs.map((s) => [this.index.get(s.end.id), s.end.port, s.io]);
    this.direct = new Uint8Array(nets.length);
    this.parent = new Int32Array(parts.length);
    // labels: one per stub, in the face layer the stub leaves through
    this.isLabel = new Uint8Array(parts.length);
    this.stubLabel = new Array(stubs.length).fill(-1);
    parts.forEach((p, i) => { if (p.label) { this.isLabel[i] = 1; this.stubLabel[p.label.stub] = i; } });
  }
  inBox(c) { const [X, Y, Z] = this.box; return c[0] >= 0 && c[1] >= 0 && c[2] >= 0 && c[0] < X && c[1] < Y && c[2] < Z; }
  idx(c) { const [, Y, Z] = this.box; return (c[0] * Y + c[1]) * Z + c[2]; }
  at(c) { return this.inBox(c) ? this.grid[this.idx(c)] : -2; }
  geo(i) { const p = this.parts[i]; const v = p.vars[p.v]; return geometry(p.type, v.k, v.mir); }
  fits(i, o, g) {
    const [X, Y, Z] = this.box;
    if (this.flat && o[1] !== 0) return false;
    for (const c of g.cells) {
      const x = o[0] + c[0], y = o[1] + c[1], z = o[2] + c[2];
      if (x < 0 || y < 0 || z < 0 || x >= X || y >= Y || z >= Z) return false;
      const id = (x * Y + y) * Z + z, a = this.grid[id];
      if ((a !== -1 && a !== i) || this.tailOwner[id] >= 0) return false;
    }
    return true;
  }

  // ---- I/O buses ----
  // A bus is a row of stub ends on one z face. The end cells sit side by side (one label width apart), each with
  // its label directly above or below it; each cable runs straight out through its end cell, arriving from the goal
  // cell just inside it. A bus too wide for the box wraps onto further rows, three cells apart (label line, end
  // line, label line). A flat bus is one row on the floor: each label lies beside its end, before its first letter
  // (the end is left of the text as you face the row from outside), so a slot is one cell wider than its label.
  busLayout(b) {
    const X = this.box[0], slots = [];
    let dx = 0, row = 0, width = 0;
    for (const si of b.members) {
      const w = this.parts[this.stubLabel[si]].label.w + (this.flat ? 1 : 0);
      if (dx + w > X && dx > 0 && !this.flat) { row++; dx = 0; }
      slots.push({ si, dx, row, w });
      dx += w;
      if (dx > width) width = dx;
    }
    return { slots, rows: row + 1, width };
  }
  busExit(li) {
    const p = this.parts[li];
    return [p.o[0] + p.label.exitDx, p.o[1] + (this.flat ? 0 : p.label.down ? 1 : -1), p.o[2]];
  }
  busGoal(li) { const e = this.busExit(li); return [e[0], e[1], e[2] + this.parts[li].label.back]; }
  busPlace(b) {
    const [X, Y, Z] = this.box, lay = this.busLayout(b);
    if (b.x0 < 0 || b.x0 + lay.width > X) return false;
    const zf = b.face === '-z' ? 0 : Z - 1, s = b.face === '-z' ? 1 : -1;
    const free = (x, y, z) => {
      if (y < 0 || y >= Y) return false;
      const id = (x * Y + y) * Z + z; return this.grid[id] === -1 && this.tailOwner[id] < 0;
    };
    const labels = [], tails = [];
    for (const sl of lay.slots) {
      const li = this.stubLabel[sl.si], lab = this.parts[li].label, down = b.down.has(sl.si);
      const ey = this.flat ? 0 : b.y0 + 3 * sl.row + 1;
      const o = this.flat ? [b.x0 + sl.dx + (b.face === '-z' ? 1 : 0), 0, zf] : [b.x0 + sl.dx, down ? ey - 1 : ey + 1, zf];
      for (let x = 0; x < lab.w; x++) if (!free(o[0] + x, o[1], zf)) return false;
      const ex = o[0] + lab.exitDx;
      if (!free(ex, ey, zf) || !free(ex, ey, zf + s)) return false;
      labels.push([li, o, down]);
      tails.push([sl.si, (ex * Y + ey) * Z + zf, 1], [sl.si, (ex * Y + ey) * Z + zf + s, 2]);
    }
    for (const [li, o, down] of labels) { this.parts[li].o = o; this.parts[li].label.down = down; this.stamp(li, li); }
    for (const [si, id, kind] of tails) { this.tailOwner[id] = si; this.tailKind[id] = kind; }
    b.tails = tails.map((t) => t[1]); b.width = lay.width; b.rows = lay.rows;
    return true;
  }
  busUnstamp(b) {
    for (const si of b.members) this.stamp(this.stubLabel[si], -1);
    for (const id of b.tails || []) { this.tailOwner[id] = -1; this.tailKind[id] = 0; }
    b.tails = [];
  }
  // Make cells (and their neighbours) expensive for parts to occupy, so the next anneal opens room there.
  // Flat: parts lie only at y = 0, so a hot cell counts on the floor cell under it.
  markHot(cells, w) {
    const [X, Y, Z] = this.box;
    if (!this.hot) this.hot = new Float32Array(X * Y * Z);
    for (let v of cells) {
      const z = v % Z, t = (v - z) / Z, x = (t - t % Y) / Y;
      let y = t % Y;
      if (this.flat) { y = 0; v = x * Y * Z + z; }
      this.hot[v] += w;
      for (const d of DIRS) {
        const nx = x + d[0], ny = y + d[1], nz = z + d[2];
        if (nx >= 0 && ny >= 0 && nz >= 0 && nx < X && ny < Y && nz < Z) this.hot[(nx * Y + ny) * Z + nz] += w / 2;
      }
    }
  }
  busState(b) { return { x0: b.x0, y0: b.y0, members: b.members.slice(), down: new Set(b.down) }; }
  busRestore(b, st) {
    this.busUnstamp(b);
    Object.assign(b, { x0: st.x0, y0: st.y0, members: st.members.slice(), down: new Set(st.down) });
    if (!this.busPlace(b)) throw new Error('bus restore failed');
  }
  // Slide the whole bus, swap two of its ends of the same kind (inputs stay together, outputs stay together), or
  // move one label to the other side of its end. Returns the previous state, or null (and no change) when the move
  // does not fit.
  busMove(b, rng) {
    const [X, Y] = this.box, st = this.busState(b);
    this.busUnstamp(b);
    const r = rng(), n = b.members.length;
    if (r < 0.3 && n > 1) {
      const a = Math.floor(rng() * n), c = Math.floor(rng() * n);
      if (a === c || this.stubs[b.members[a]].io !== this.stubs[b.members[c]].io) { this.busRestore(b, st); return null; }
      [b.members[a], b.members[c]] = [b.members[c], b.members[a]];
    } else if (r < 0.5 && !this.flat) {
      const si = b.members[Math.floor(rng() * n)];
      if (b.down.has(si)) b.down.delete(si); else b.down.add(si);
    } else if (r < 0.85) {
      b.x0 += Math.round((rng() * 2 - 1) * 2); if (!this.flat) b.y0 += Math.round((rng() * 2 - 1) * 1);
    } else {
      b.x0 = Math.floor(rng() * Math.max(1, X - (b.width || 0) + 1)); if (!this.flat) b.y0 = Math.floor(rng() * (Y + 1)) - 1;
    }
    if (!this.busPlace(b)) { this.busRestore(b, st); return null; }
    return st;
  }
  stamp(i, val) {
    const [, Y, Z] = this.box, o = this.parts[i].o, g = this.geo(i);
    for (const c of g.cells) {
      const x = o[0] + c[0], y = o[1] + c[1], z = o[2] + c[2];
      this.grid[(x * Y + y) * Z + z] = val;
      // flat: the cells above a label are closed too, so its text stays in view
      if (this.flat && this.isLabel[i] && c[1] === g.dims[1] - 1) for (let u = y + 1; u < Y; u++) this.grid[(x * Y + u) * Z + z] = val;
    }
  }
  worldPort(i, name) {
    const p = this.geo(i).ports[name], o = this.parts[i].o;
    return { cell: vadd(o, p.cell), face: vadd(o, p.face), inward: p.inward, dir: p.dir };
  }

  // Full evaluation. With full = true it also lists problems and which nets are direct contacts.
  evaluate(full = false) {
    const { parts, grid, portOwner } = this;
    const [X, Y, Z] = this.box;
    let cost = 0;
    const direct = this.direct; direct.fill(0);
    const touched = [];
    const problems = full ? [] : null;
    // flat: every used port's cell up front, so a port does not count its neighbour's port cell as a way out
    let mark = null;
    const marked = [];
    if (this.flat) {
      if (!this.mark) this.mark = new Int32Array(X * Y * Z).fill(-1);
      mark = this.mark;
      for (let i = 0; i < parts.length; i++) {
        const g = this.geo(i), o = parts[i].o;
        for (const q of g.portList) {
          const r = this.role[i][q.name];
          if (!r) continue;
          const cx = o[0] + q.cell[0], cy = o[1] + q.cell[1], cz = o[2] + q.cell[2];
          if (cx < 0 || cy < 0 || cz < 0 || cx >= X || cy >= Y || cz >= Z) continue;
          const ci = (cx * Y + cy) * Z + cz;
          mark[ci] = r.net !== undefined ? r.net : -2 - r.stub; marked.push(ci);
        }
      }
    }
    for (let i = 0; i < parts.length; i++) {
      const g = this.geo(i), o = parts[i].o, role = this.role[i];
      for (const q of g.portList) {
        const cx = o[0] + q.cell[0], cy = o[1] + q.cell[1], cz = o[2] + q.cell[2];
        const inside = cx >= 0 && cy >= 0 && cz >= 0 && cx < X && cy < Y && cz < Z;
        const ci = inside ? (cx * Y + cy) * Z + cz : -1;
        const occ = inside ? grid[ci] : -2;
        const r = role[q.name];
        if (occ >= 0 && occ !== i) {
          // something sits in this port's cell: a mutual port contact connects, a plain face blocks
          const oo = parts[occ].o, fx = o[0] + q.face[0], fy = o[1] + q.face[1], fz = o[2] + q.face[2];
          let mate = null;
          for (const m of this.geo(occ).portList) {
            if (oo[0] + m.face[0] === cx && oo[1] + m.face[1] === cy && oo[2] + m.face[2] === cz &&
                oo[0] + m.cell[0] === fx && oo[1] + m.cell[1] === fy && oo[2] + m.cell[2] === fz) { mate = m; break; }
          }
          if (mate) {
            const r2 = this.role[occ][mate.name];
            if (r && r2 && r.net !== undefined && r.net === r2.net) direct[r.net] = 1;
            else { cost += BIG; if (full) problems.push(`unrelated ports touch: ${parts[i].id}.${q.name} / ${parts[occ].id}.${mate.name}`); }
          } else if (r) { cost += BIG; if (full) problems.push(`port blocked: ${parts[i].id}.${q.name}`); }
        } else if (r) {
          if (!inside) { cost += BIG; if (full) problems.push(`port outside box: ${parts[i].id}.${q.name}`); continue; }
          // a bus cable cell may only be this stub's own goal cell
          const to = this.tailOwner[ci];
          if (to >= 0 && !(r.stub === to && this.tailKind[ci] === 2)) {
            cost += BIG; if (full) problems.push(`port ${parts[i].id}.${q.name} opens onto a bus cable cell`);
          }
          const owner = r.net !== undefined ? r.net : -2 - r.stub;
          const prev = portOwner[ci];
          if (prev !== -1 && prev !== owner) { cost += BIG; if (full) problems.push(`two nets share a port cell at ${cx},${cy},${cz}`); }
          portOwner[ci] = owner; touched.push(ci);
          // the cable leaving this port needs at least one free neighbouring cell (or the partner's port cell); flat:
          // not another cable's port or bus cell
          let exits = 0;
          for (let d = 0; d < 6; d++) {
            if (d === q.inward) continue;
            const nx = cx + DIRS[d][0], ny = cy + DIRS[d][1], nz = cz + DIRS[d][2];
            if (nx < 0 || ny < 0 || nz < 0 || nx >= X || ny >= Y || nz >= Z) {
              if (r.stub !== undefined && !(this.flat && DIRS[d][1] !== 0)) exits++;
              continue;
            }
            const nb = (nx * Y + ny) * Z + nz, tail = this.tailOwner[nb];
            if (grid[nb] === -1 && (!mark || ((tail < 0 || tail === r.stub) && (mark[nb] === -1 || mark[nb] === owner)))) exits++;
          }
          if (exits === 0) { cost += 60; if (full) problems.push(`port boxed in: ${parts[i].id}.${q.name}`); }
          else if (exits === 1) cost += 4;
        }
      }
    }
    for (const ci of touched) portOwner[ci] = -1;
    for (const ci of marked) mark[ci] = -1;
    const usedPortCells = touched;
    let wire = 0, longest = 0;
    for (let ni = 0; ni < this.netEnds.length; ni++) {
      if (direct[ni]) continue;
      const [ia, pa, ib, pb] = this.netEnds[ni];
      const oa = parts[ia].o, ob = parts[ib].o, qa = this.geo(ia).ports[pa], qb = this.geo(ib).ports[pb];
      const len = Math.abs(oa[0] + qa.cell[0] - ob[0] - qb.cell[0]) + Math.abs(oa[1] + qa.cell[1] - ob[1] - qb.cell[1]) +
        Math.abs(oa[2] + qa.cell[2] - ob[2] - qb.cell[2]) + 1;
      wire += len; if (len > longest) longest = len;
      cost += NET_OVERHEAD;
      if (len > this.maxNet - 5) cost += 50 * (len - this.maxNet + 5);
    }
    for (let si = 0; si < this.stubEnds.length; si++) {
      const [ia, pa] = this.stubEnds[si];
      const po = parts[ia].o, pq = this.geo(ia).ports[pa].cell;
      const px = po[0] + pq[0], py = po[1] + pq[1], pz = po[2] + pq[2];
      const li = this.stubLabel[si], lab = li >= 0 ? parts[li].label : null, onBus = lab && lab.bus !== undefined;
      let len;
      if (onBus) {
        // a bus stub runs to its goal cell, then one straight cell out through the face
        const g = this.busGoal(li);
        len = Math.abs(px - g[0]) + Math.abs(py - g[1]) + Math.abs(pz - g[2]) + 2;
      } else len = (this.stubs[si].face === '-z' ? pz : Z - 1 - pz) + 1;
      wire += len;
      if (len > this.maxStub - 3) cost += 50 * (len - this.maxStub + 3);
      if (!lab) continue;
      const lpo = parts[li].o;
      let loose = 0, near = Infinity;
      for (const c of this.geo(li).cells) {
        const x = lpo[0] + c[0], y = lpo[1] + c[1], z = lpo[2] + c[2] + lab.back;
        const occ = z >= 0 && z < Z ? grid[(x * Y + y) * Z + z] : -1;
        if (occ < 0 || this.isLabel[occ]) loose++;
        if (!onBus) { const d = Math.abs(x - px) + Math.abs(y - py); if (d < near) near = d; }
      }
      if (this.flat) loose = 0;                        // a label lying on the floor is held by the floor
      if (onBus) {
        // a bus label is one plate held by its back face: at least half of that face must rest on parts
        const short = Math.max(0, loose - Math.floor(lab.w / 2));
        cost += 25 * short + 3 * loose;
        if (full && short) problems.push(`label for ${this.stubs[si].label} is not backed by a part`);
      } else {
        cost += 25 * loose + 2 * near;
        if (full && loose) problems.push(`label for ${this.stubs[si].label} is not backed by a part`);
      }
    }
    cost += wire;
    for (const p of parts) if (!p.vars[p.v].upright) cost += 1;
    // compactness: frame quarters spanned by the parts (z always spans the whole box for the stubs; a flat layout
    // counts as one quarter high)
    {
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      for (let i = 0; i < parts.length; i++) {
        const o = parts[i].o, d = this.geo(i).dims;
        if (o[0] < x0) x0 = o[0]; if (o[1] < y0) y0 = o[1];
        if (o[0] + d[0] > x1) x1 = o[0] + d[0]; if (o[1] + d[1] > y1) y1 = o[1] + d[1];
      }
      cost += 6 * ((x1 - x0) / 4) * (this.flat ? 1 : (y1 - y0) / 4) * (Z / 4);
    }
    // reachability: a cable's two ends must reach a common free region (other cables' port cells are walls),
    // and a stub's region must reach its face
    if (this.regionCheck || full) {
      const sealed = this.sealedCables(usedPortCells, direct);
      cost += 80 * sealed;
      if (full && sealed) problems.push(`${sealed} cables have no free route between their ends`);
    }
    // routing repair: parts are pushed off the cells where the last routing attempt ran out of room
    if (this.hot) {
      const hot = this.hot;
      for (let i = 0; i < parts.length; i++) {
        if (this.isLabel[i]) continue;
        const o = parts[i].o;
        for (const c of this.geo(i).cells) cost += hot[((o[0] + c[0]) * Y + o[1] + c[1]) * Z + o[2] + c[2]];
      }
    }
    // structural: every part must touch the rest (face contact); on a flat floor the floor holds them
    const comp = this.flat ? 1 : this.components();
    cost += 40 * (comp - 1);
    if (full) return { cost, direct: Array.from(direct, (d) => d === 1), wire, longest, components: comp, problems };
    return cost;
  }

  // How many cables (not direct contacts) cannot reach their other end, or their face or goal cell, through free
  // cells.
  sealedCables(usedPortCells, direct) {
    const parts = this.parts, [X, Y, Z] = this.box;
    const walls = usedPortCells.slice();             // bus end and goal cells belong to their stub: walls too
    for (const b of this.buses) for (const id of b.tails || []) walls.push(id);
    const { region, touchIn, touchOut } = this.regions(walls);
    const exits = (i, name) => {
      const o = parts[i].o, q = this.geo(i).ports[name], c = [o[0] + q.cell[0], o[1] + q.cell[1], o[2] + q.cell[2]];
      const out = [];
      for (let d = 0; d < 6; d++) {
        if (d === q.inward) continue;
        const nx = c[0] + DIRS[d][0], ny = c[1] + DIRS[d][1], nz = c[2] + DIRS[d][2];
        if (nx < 0 || ny < 0 || nz < 0 || nx >= X || ny >= Y || nz >= Z) continue;
        const rr = region[(nx * Y + ny) * Z + nz];
        if (rr >= 0) out.push(rr);
      }
      return { c, out };
    };
    let sealed = 0;
    for (let ni = 0; ni < this.netEnds.length; ni++) {
      if (direct[ni]) continue;
      const [ia, pa, ib, pb] = this.netEnds[ni];
      const A = exits(ia, pa), B = exits(ib, pb);
      const dist = Math.abs(A.c[0] - B.c[0]) + Math.abs(A.c[1] - B.c[1]) + Math.abs(A.c[2] - B.c[2]);
      if (dist <= 1) continue;
      if (!A.out.some((r) => B.out.includes(r))) sealed++;
    }
    for (let si = 0; si < this.stubEnds.length; si++) {
      const [ia, pa] = this.stubEnds[si];
      const A = exits(ia, pa);
      const li = this.stubLabel[si];
      if (li >= 0 && parts[li].label.bus !== undefined) {
        // the goal cell is a wall for every other cable; this stub reaches it through any free neighbour
        const g = this.busGoal(li);
        if (veq(A.c, g)) continue;
        let reach = false;
        for (let d = 0; d < 6 && !reach; d++) {
          const nx = g[0] + DIRS[d][0], ny = g[1] + DIRS[d][1], nz = g[2] + DIRS[d][2];
          if (nx === A.c[0] && ny === A.c[1] && nz === A.c[2]) reach = true;
          else if (nx >= 0 && ny >= 0 && nz >= 0 && nx < X && ny < Y && nz < Z) {
            const rr = region[(nx * Y + ny) * Z + nz];
            if (rr >= 0 && A.out.includes(rr)) reach = true;
          }
        }
        if (!reach) sealed++;
        continue;
      }
      const inFace = this.stubs[si].face === '-z';
      if (A.c[2] === (inFace ? 0 : Z - 1)) continue;
      if (!A.out.some((r) => (inFace ? touchIn[r] : touchOut[r]))) sealed++;
    }
    return sealed;
  }

  // Label the connected regions of free cells; returns per-region flags for touching the -z / +z faces.
  regions(walls) {
    const [X, Y, Z] = this.box, N = X * Y * Z, grid = this.grid;
    if (!this.region) { this.region = new Int32Array(N); this.queue = new Int32Array(N); }
    const region = this.region, queue = this.queue;
    region.fill(-1);
    if (walls) for (const w of walls) region[w] = -2;   // used port cells: only their own cable may pass
    const touchIn = [], touchOut = [];
    let id = 0;
    for (let s = 0; s < N; s++) {
      if (grid[s] !== -1 || region[s] !== -1) continue;
      let head = 0, tail = 0, tin = false, tout = false;
      queue[tail++] = s; region[s] = id;
      while (head < tail) {
        const v = queue[head++];
        const z = v % Z, xy = (v - z) / Z, y = xy % Y, x = (xy - y) / Y;
        if (z === 0) tin = true;
        if (z === Z - 1) tout = true;
        if (x > 0) { const u = v - Y * Z; if (grid[u] === -1 && region[u] === -1) { region[u] = id; queue[tail++] = u; } }
        if (x < X - 1) { const u = v + Y * Z; if (grid[u] === -1 && region[u] === -1) { region[u] = id; queue[tail++] = u; } }
        if (y > 0) { const u = v - Z; if (grid[u] === -1 && region[u] === -1) { region[u] = id; queue[tail++] = u; } }
        if (y < Y - 1) { const u = v + Z; if (grid[u] === -1 && region[u] === -1) { region[u] = id; queue[tail++] = u; } }
        if (z > 0) { const u = v - 1; if (grid[u] === -1 && region[u] === -1) { region[u] = id; queue[tail++] = u; } }
        if (z < Z - 1) { const u = v + 1; if (grid[u] === -1 && region[u] === -1) { region[u] = id; queue[tail++] = u; } }
      }
      touchIn.push(tin); touchOut.push(tout);
      id++;
    }
    return { region, touchIn, touchOut };
  }

  // Groups of logic parts joined by face contact through a joint area; a part none of whose own joint areas touches
  // another part is not held and counts as a group of its own. Labels do not count: a label hangs on its back face
  // and holds nothing together.
  components() {
    const n = this.parts.length, parent = this.parent, isLabel = this.isLabel;
    for (let i = 0; i < n; i++) parent[i] = i;
    const find = (x) => { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
    const [X, Y, Z] = this.box, grid = this.grid;
    let loose = 0;
    for (let i = 0; i < n; i++) {
      if (isLabel[i]) continue;
      const o = this.parts[i].o;
      let held = false;
      for (const c of this.geo(i).jointShell) {
        const x = o[0] + c[0], y = o[1] + c[1], z = o[2] + c[2];
        if (x < 0 || y < 0 || z < 0 || x >= X || y >= Y || z >= Z) continue;
        const occ = grid[(x * Y + y) * Z + z];
        if (occ >= 0 && occ !== i && !isLabel[occ]) { held = true; const a = find(i), b = find(occ); if (a !== b) parent[a] = b; }
      }
      if (!held && n > 1) loose++;
    }
    let k = 0;
    for (let i = 0; i < n; i++) if (!isLabel[i] && find(i) === i) k++;
    return k + loose;
  }
}

// Origins (with variants) that put part i's port `name` face to face with part j's port `jName`
// (gap = 0: direct contact), or one empty cell apart facing each other (gap = 1: a 1-cell cable).
function snapTargets(L, i, name, j, jName, gap) {
  const pj = L.parts[j], qj = L.geo(j).ports[jName];
  const jCell = vadd(pj.o, qj.cell), jFace = vadd(pj.o, qj.face);
  const p = L.parts[i], out = [];
  for (let v = 0; v < p.vars.length; v++) {
    const q = geometry(p.type, p.vars[v].k, p.vars[v].mir).ports[name];
    if (q.inward !== opposite(qj.inward)) continue;          // the two ports must face each other
    const o = gap === 0 ? vsub(jCell, q.face) : vsub(jCell, q.cell);
    if (gap === 0 && !veq(vadd(o, q.cell), jFace)) continue;
    out.push({ v, o });
  }
  return out;
}

// Origins (with variants) that put part i's port `name` on cell c: its cable starts right there.
function portOnCell(L, i, name, c) {
  const p = L.parts[i], out = [];
  for (let v = 0; v < p.vars.length; v++) out.push({ v, o: vsub(c, geometry(p.type, p.vars[v].k, p.vars[v].mir).ports[name].cell) });
  return out;
}

function initialPlacement(L, rng) {
  // signal-flow order; each part goes face to face with a driver that is already placed if it can,
  // else one cell from it, else near it, else anywhere
  const [X, Y, Z] = L.box;
  const order = L.parts.map((_, i) => i).sort((a, b) => L.parts[a].level - L.parts[b].level || a - b);
  const done = new Set();
  const drivers = L.parts.map(() => []);
  for (const [ia, pa, ib, pb] of L.netEnds) drivers[ib].push([ia, pa, pb]);
  // buses first, anywhere on their face; the parts then settle around them
  for (const b of L.buses) {
    const lay = L.busLayout(b);
    if (lay.width > X || (!L.flat && 3 * lay.rows - 1 > Y)) return false;
    let ok = false;
    for (let tries = 0; tries < 2000 && !ok; tries++) {
      b.x0 = Math.floor(rng() * (X - lay.width + 1)); b.y0 = L.flat ? 0 : Math.floor(rng() * (Y + 1)) - 1;
      ok = L.busPlace(b);
    }
    if (!ok) return false;
    for (const si of b.members) done.add(L.stubLabel[si]);
  }
  // then each bus stub's part right behind its slot, its port on the slot's goal cell (where it can, it also holds
  // the slot's label)
  for (const b of L.buses) for (const si of b.members.slice().sort(() => rng() - 0.5)) {
    const [ia, pa] = L.stubEnds[si];
    if (done.has(ia)) continue;
    for (const t of portOnCell(L, ia, pa, L.busGoal(L.stubLabel[si])).sort(() => rng() - 0.5)) {
      L.parts[ia].v = t.v;
      if (L.fits(ia, t.o, L.geo(ia))) { L.parts[ia].o = t.o; L.stamp(ia, ia); done.add(ia); break; }
    }
  }
  for (const i of order) {
    if (done.has(i)) continue;
    if (L.parts[i].label) {
      const p = L.parts[i], g = L.geo(i), z = p.label.back > 0 ? 0 : Z - 1;
      let ok = false;
      for (let tries = 0; tries < 4000 && !ok; tries++) {
        const o = [Math.floor(rng() * (X - g.dims[0] + 1)), L.flat ? 0 : Math.floor(rng() * (Y - g.dims[1] + 1)), z];
        if (L.fits(i, o, g)) { p.o = o; L.stamp(i, i); ok = true; }
      }
      if (!ok) return false;
      done.add(i);
      continue;
    }
    let placed = false;
    const p = L.parts[i];
    const placedDrivers = drivers[i].filter(([ia]) => done.has(ia));
    for (const gap of [0, 1]) {
      for (const [ia, pa, pb] of placedDrivers) {
        const ts = snapTargets(L, i, pb, ia, pa, gap);
        for (const t of ts.sort(() => rng() - 0.5)) {
          p.v = t.v;
          if (L.fits(i, t.o, L.geo(i))) { p.o = t.o; L.stamp(i, i); placed = true; break; }
        }
        if (placed) break;
      }
      if (placed) break;
    }
    for (let tries = 0; tries < 400 && !placed && placedDrivers.length; tries++) {
      const near = L.parts[placedDrivers[0][0]].o;
      p.v = Math.floor(rng() * p.vars.length);
      const g = L.geo(i);
      const o = [0, 1, 2].map((a) => (a === 1 && L.flat ? 0 : near[a] + Math.round((rng() * 2 - 1) * 4)));
      if (L.fits(i, o, g)) { p.o = o; L.stamp(i, i); placed = true; }
    }
    if (placed) { done.add(i); continue; }
    // near its level's place along z (a flat layout widens this to the whole box once that band is full)
    for (let tries = 0; tries < (L.flat ? 8000 : 4000) && !placed; tries++) {
      const p = L.parts[i];
      p.v = Math.floor(rng() * p.vars.length);
      const g = L.geo(i);
      const lv = p.level / Math.max(1, L.maxLevel);
      const z = tries >= 4000 ? Math.floor(rng() * (Z - g.dims[2] + 1))
        : Math.max(0, Math.min(Z - g.dims[2], Math.round(lv * (Z - g.dims[2]) + (rng() - 0.5) * 4)));
      const o = [Math.floor(rng() * (X - g.dims[0] + 1)), L.flat ? 0 : Math.floor(rng() * (Y - g.dims[1] + 1)), z];
      if (L.fits(i, o, g)) { p.o = o; L.stamp(i, i); placed = true; }
    }
    if (!placed) return false;
    done.add(i);
  }
  return true;
}

// opts.T0 / opts.T1: start and end temperature (a repair pass starts cool and keeps the layout's shape)
function anneal(L, rng, steps, opts = {}) {
  const n = L.parts.length;
  let cur = L.evaluate();
  const snapshot = () => ({ parts: L.parts.map((p) => ({ v: p.v, o: p.o.slice() })), buses: L.buses.map((b) => L.busState(b)) });
  let best = cur, bestState = snapshot();
  const T0 = opts.T0 ?? 12, T1 = opts.T1 ?? 0.2;
  const [X, Y, Z] = L.box;
  const nets = L.netEnds;
  const busStubs = L.stubs.map((_, si) => si).filter((si) => L.stubLabel[si] >= 0 && L.parts[L.stubLabel[si]].label.bus !== undefined);
  for (let s = 0; s < steps; s++) {
    const T = T0 * Math.pow(T1 / T0, s / steps);
    // (flat: the cable level over the parts nearly always joins everything, so only the final check looks)
    if (s === Math.floor(steps * 0.6) && !L.regionCheck && !L.flat) { L.regionCheck = true; cur = L.evaluate(); best = Infinity; }
    const r = rng();
    let i, j = -1, oldJ = null, target = null;
    if (r < 0.25 && nets.length) {
      // snap one end of a random net against the other
      const [ia, pa, ib, pb] = nets[Math.floor(rng() * nets.length)];
      const flip = rng() < 0.5, gap = rng() < 0.8 ? 0 : 1;
      i = flip ? ia : ib;
      const ts = flip ? snapTargets(L, ia, pa, ib, pb, gap) : snapTargets(L, ib, pb, ia, pa, gap);
      if (!ts.length) continue;
      target = ts[Math.floor(rng() * ts.length)];
    } else if (r < 0.31 && busStubs.length) {
      // put a bus stub's part right behind its slot: its port on the slot's goal cell
      const si = busStubs[Math.floor(rng() * busStubs.length)];
      const [ia, pa] = L.stubEnds[si];
      i = ia;
      const ts = portOnCell(L, ia, pa, L.busGoal(L.stubLabel[si]));
      target = ts[Math.floor(rng() * ts.length)];
    } else i = Math.floor(rng() * n);
    if (L.isLabel[i] && L.parts[i].label.bus !== undefined) {
      // a bus label moves its whole bus: slide it, or swap two of its ends
      const b = L.buses[L.parts[i].label.bus];
      const prev = L.busMove(b, rng);
      if (!prev) continue;
      const c = L.evaluate();
      if (c <= cur || rng() < Math.exp((cur - c) / T)) {
        cur = c;
        if (c < best) { best = c; bestState = snapshot(); }
      } else L.busRestore(b, prev);
      continue;
    }
    const p = L.parts[i];
    const old = { v: p.v, o: p.o };
    L.stamp(i, -1);
    if (target) {
      p.v = target.v;
      if (!L.fits(i, target.o, L.geo(i))) { p.v = old.v; L.stamp(i, i); continue; }
      p.o = target.o;
      L.stamp(i, i);
    } else if (r < 0.37 && n > 1) {
      // swap with another part
      j = Math.floor(rng() * n);
      if (j === i || L.isLabel[i] || L.isLabel[j]) { L.stamp(i, i); j = -1; continue; }
      const q = L.parts[j];
      oldJ = { v: q.v, o: q.o };
      L.stamp(j, -1);
      p.o = oldJ.o; q.o = old.o;
      let ok = L.fits(i, p.o, L.geo(i));
      if (ok) { L.stamp(i, i); ok = L.fits(j, q.o, L.geo(j)); if (!ok) L.stamp(i, -1); }
      if (ok) L.stamp(j, j); else { p.o = old.o; q.o = oldJ.o; L.stamp(j, j); L.stamp(i, i); continue; }
    } else {
      if (r < 0.52) p.v = Math.floor(rng() * p.vars.length);
      const g = L.geo(i);
      let o;
      if (r < 0.6) o = [Math.floor(rng() * (X - g.dims[0] + 1)), Math.floor(rng() * (Y - g.dims[1] + 1)), Math.floor(rng() * (Z - g.dims[2] + 1))];
      else {
        const span = r < 0.85 ? 1 : 3;
        o = [old.o[0] + Math.round((rng() * 2 - 1) * span), old.o[1] + Math.round((rng() * 2 - 1) * span), old.o[2] + Math.round((rng() * 2 - 1) * span)];
      }
      if (L.isLabel[i]) o[2] = old.o[2];        // labels only slide over their face
      if (L.flat) o[1] = 0;
      if (!L.fits(i, o, g)) { p.v = old.v; L.stamp(i, i); continue; }
      p.o = o;
      L.stamp(i, i);
    }
    const c = L.evaluate();
    if (c <= cur || rng() < Math.exp((cur - c) / T)) {
      cur = c;
      if (c < best) { best = c; bestState = snapshot(); }
    } else {
      L.stamp(i, -1);
      if (j >= 0) { L.stamp(j, -1); L.parts[j].v = oldJ.v; L.parts[j].o = oldJ.o; }
      p.v = old.v; p.o = old.o;
      L.stamp(i, i);
      if (j >= 0) L.stamp(j, j);
    }
  }
  L.grid.fill(-1); L.tailOwner.fill(-1); L.tailKind.fill(0);
  L.parts.forEach((p, i) => { p.v = bestState.parts[i].v; p.o = bestState.parts[i].o; });
  L.parts.forEach((p, i) => { if (!(p.label && p.label.bus !== undefined)) L.stamp(i, i); });
  L.buses.forEach((b, bi) => {
    const st = bestState.buses[bi];
    Object.assign(b, { x0: st.x0, y0: st.y0, members: st.members.slice(), down: new Set(st.down) });
    b.tails = [];
    if (!L.busPlace(b)) throw new Error('bus does not fit back into the best layout');
  });
  return best;
}

// ---------- routing (PathFinder) ----------
class Heap {
  constructor() { this.a = []; }
  push(f, v) {
    const a = this.a; a.push([f, v]);
    let i = a.length - 1;
    while (i > 0) { const p = (i - 1) >> 1; if (a[p][0] <= a[i][0]) break; [a[p], a[i]] = [a[i], a[p]]; i = p; }
  }
  pop() {
    const a = this.a, top = a[0], last = a.pop();
    if (a.length) {
      a[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1, r = l + 1;
        let m = i;
        if (l < a.length && a[l][0] < a[m][0]) m = l;
        if (r < a.length && a[r][0] < a[m][0]) m = r;
        if (m === i) break;
        [a[m], a[i]] = [a[i], a[m]]; i = m;
      }
    }
    return top;
  }
  get size() { return this.a.length; }
}

function route(L, direct, opts = {}) {
  const [X, Y, Z] = L.box;
  const N = X * Y * Z;
  const decode = (v) => { const z = v % Z, t = (v - z) / Z, y = t % Y; return [(t - y) / Y, y, z]; };
  // jobs: internal nets that are not direct contacts, and every stub
  const jobs = [];
  const reserved = new Int32Array(N).fill(-1);  // used port cells belong to their job
  L.nets.forEach((n, ni) => {
    if (direct[ni]) return;
    const a = L.worldPort(L.index.get(n.a.id), n.a.port), b = L.worldPort(L.index.get(n.b.id), n.b.port);
    jobs.push({ kind: 'net', ref: ni, src: a, dst: b, limit: L.maxNet });
  });
  L.stubs.forEach((s, si) => {
    const a = L.worldPort(L.index.get(s.end.id), s.end.port);
    const job = { kind: 'stub', ref: si, src: a, io: s.io, limit: L.maxStub, out: s.face === '-z' ? 5 : 4 };
    const li = L.stubLabel[si];
    if (li >= 0 && L.parts[li].label.bus !== undefined) {
      // bus: route to the goal cell; the straight end cell after it is fixed
      job.targets = [L.busGoal(li)];
      job.tail = [L.busExit(li)];
      job.limit = L.maxStub - 1;
    } else if (li >= 0) {
      const lp = L.parts[li], cells = L.geo(li).cells.map((c) => vadd(lp.o, c));
      const own = new Set(cells.map((c) => c.join()));
      const targets = [];
      for (const c of cells) for (const d of [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0]]) {
        const w = vadd(c, d);
        if (L.inBox(w) && !own.has(w.join()) && L.grid[L.idx(w)] === -1) targets.push(w);
      }
      if (targets.length) job.targets = targets;
    }
    jobs.push(job);
  });
  jobs.forEach((j, ji) => {
    reserved[L.idx(j.src.cell)] = ji;
    if (j.dst) reserved[L.idx(j.dst.cell)] = ji;
    if (j.tail) { reserved[L.idx(j.targets[0])] = ji; for (const c of j.tail) reserved[L.idx(c)] = -2; }
  });
  const hist = new Float32Array(N);
  const occ = new Int32Array(N);
  const paths = new Array(jobs.length).fill(null);
  const free = (c) => L.grid[c] === -1;
  // flat: a cable cell one up costs a little more, so cables stay on the floor where that costs nothing (there the
  // deck anchors them)
  const raised = L.flat ? 2 : 0;
  const unusedPort = new Uint8Array(N);
  L.parts.forEach((p, i) => {
    for (const q of L.geo(i).portList) {
      const c = vadd(p.o, q.cell);
      if (L.inBox(c) && !L.role[i][q.name]) unusedPort[L.idx(c)] = 1;
    }
  });
  const stride = [Y * Z, Z, 1];
  function astar(ji, pf) {
    const j = jobs[ji];
    const s = L.idx(j.src.cell);
    const goal = j.dst ? L.idx(j.dst.cell) : -1;
    const tz = j.out === 5 ? 0 : Z - 1;
    const tset = j.targets ? new Set(j.targets.map((c) => L.idx(c))) : null;
    const hfun = j.dst
      ? (v) => { const c = decode(v); return Math.abs(c[0] - j.dst.cell[0]) + Math.abs(c[1] - j.dst.cell[1]) + Math.abs(c[2] - j.dst.cell[2]); }
      : tset ? (v) => { const c = decode(v); let m = Infinity; for (const w of j.targets) { const d = Math.abs(c[0] - w[0]) + Math.abs(c[1] - w[1]) + Math.abs(c[2] - w[2]); if (d < m) m = d; } return m; }
      : (v) => Math.abs(decode(v)[2] - tz);
    const isGoal = j.dst ? (v) => v === goal : tset ? (v) => tset.has(v) : (v) => decode(v)[2] === tz;
    const g = new Map([[s, 0]]), from = new Map([[s, -1]]), len = new Map([[s, 1]]);
    const heap = new Heap();
    heap.push(hfun(s), s);
    while (heap.size) {
      const [, v] = heap.pop();
      if (isGoal(v)) {
        const path = [];
        for (let u = v; u !== -1; u = from.get(u)) path.push(u);
        return path.reverse();
      }
      const gv = g.get(v), lv = len.get(v), pv = from.get(v);
      const c = decode(v);
      for (let d = 0; d < 6; d++) {
        const n = vadd(c, DIRS[d]);
        if (!L.inBox(n)) continue;
        const u = L.idx(n);
        if (!free(u)) continue;
        if (reserved[u] !== -1 && reserved[u] !== ji) continue;
        // on a floor, reach counts from the last anchored cell: the port's cell, or a cell lying straight on the deck
        // (v is straight when its predecessor, v and u line up along the floor). Every cable ends on an anchored cell
        // (a port, or a stub's straight end on the deck), so a run between two anchors may be twice the game's 10.
        // It is a hard limit: the congestion price would otherwise outbid it.
        const lu = L.floor && (pv === -1 || (c[1] === 0 && n[1] === 0 && pv - v === v - u)) ? 1 : lv + 1;
        if (L.floor && lu > 2 * MAX_UNANCHORED) continue;
        const over = !L.floor && lu > j.limit;
        const step = (1 + hist[u] + (unusedPort[u] ? 2 : 0) + (n[1] > 0 ? raised : 0)) * (1 + pf * occ[u]) + (over ? 40 : 0);
        const gu = gv + step;
        if (gu < (g.has(u) ? g.get(u) : Infinity)) {
          g.set(u, gu); from.set(u, v); len.set(u, lu);
          heap.push(gu + hfun(u), u);
        }
      }
    }
    return null;
  }
  let pf = 0.5, lastMissing = 0, lastOver = 0;
  const order = jobs.map((_, i) => i).sort((a, b) => {
    const d = (j) => j.dst ? Math.abs(j.src.cell[0] - j.dst.cell[0]) + Math.abs(j.src.cell[1] - j.dst.cell[1]) + Math.abs(j.src.cell[2] - j.dst.cell[2]) : 0;
    return d(jobs[b]) - d(jobs[a]);
  });
  const iters = opts.iterations || 40;
  for (let it = 0; it < iters; it++) {
    for (const ji of order) {
      if (paths[ji]) for (const v of paths[ji]) occ[v]--;
      const p = astar(ji, pf);
      paths[ji] = p;
      if (p) for (const v of p) occ[v]++;
    }
    let over = 0, missing = 0;
    for (let ji = 0; ji < jobs.length; ji++) if (!paths[ji]) missing++;
    lastMissing = missing;
    for (let v = 0; v < N; v++) if (occ[v] > 1) { over++; hist[v] += 1; }
    lastOver = over;
    if (!over && !missing) {
      const long = jobs.map((_, ji) => ji).filter((ji) => paths[ji].length > jobs[ji].limit);
      if (!long.length) return { ok: true, jobs, paths: paths.map((p) => p.map(decode)), iterations: it + 1, tooLong: 0 };
      // hot cells for a placement repair: the over-long cables
      const hot = [];
      for (const ji of long) hot.push(...paths[ji]);
      return { ok: false, jobs, paths: [], iterations: it + 1, tooLong: long.length, hot };
    }
    pf *= 1.6;
  }
  // hot cells for a placement repair: the cells still shared, and both ends of every cable that found no path
  const hot = [];
  for (let v = 0; v < N; v++) if (occ[v] > 1) hot.push(v);
  jobs.forEach((j, ji) => {
    if (paths[ji]) return;
    hot.push(L.idx(j.src.cell));
    if (j.dst) hot.push(L.idx(j.dst.cell));
    if (j.targets) for (const c of j.targets) hot.push(L.idx(c));
  });
  return { ok: false, jobs, paths: [], iterations: iters, hot,
    reason: lastMissing ? `${lastMissing} cables found no path` : `${lastOver} cells still shared` };
}

// ---------- cables from paths ----------
function cablesFrom(L, routed) {
  const cables = [];
  routed.jobs.forEach((j, ji) => {
    const path = j.tail ? routed.paths[ji].concat(j.tail) : routed.paths[ji];
    const role = j.kind === 'stub' ? L.stubs[j.ref].io : 'net';
    for (let i = 0; i < path.length; i++) {
      const a = i === 0 ? j.src.inward : dirIndex(vsub(path[i - 1], path[i]));
      let b;
      if (i < path.length - 1) b = dirIndex(vsub(path[i + 1], path[i]));
      else if (j.dst) b = j.dst.inward;
      else b = j.out;                                 // the stub's open end faces out of the box
      let shape, k;
      if (b === opposite(a)) { shape = 0; k = STRAIGHT[a]; }
      else { shape = 1; k = CORNER[a * 6 + b]; }
      cables.push({ cell: path[i], shape, k, open: [a, b], role, job: ji, step: i });
    }
  });
  return cables;
}

// ---------- independent check: re-derive every connection from the cells ----------
function check(L, cables) {
  const errors = [];
  const [, , Z] = L.box;
  const cab = new Map(cables.map((c) => [c.cell.join(), c]));
  const openDirs = (c) => {
    if (c.shape === 0) { const f = dirIndex(frontOf(c.k)); return [f, opposite(f)]; }
    return [dirIndex(upOf(c.k)), dirIndex(frontOf(c.k))];
  };
  // a Wireless Transmitter's tx and rx are one physical port on one cell: compare them under one name
  const typeOf = new Map(L.parts.map((p) => [p.id, p.type]));
  const canon = (id, port) => (typeOf.get(id) === 'wireless_transmitter' ? `${id}.trx` : `${id}.${port}`);
  // ports by their outside cell
  const portAt = new Map();
  L.parts.forEach((p, i) => {
    for (const q of L.geo(i).portList) {
      const key = vadd(p.o, q.cell).join();
      if (!portAt.has(key)) portAt.set(key, []);
      portAt.get(key).push({ i, q, face: vadd(p.o, q.face) });
    }
  });
  const seen = new Set();
  const found = [];
  let farthest = 0;
  for (const c of cables) {
    const key0 = c.cell.join();
    if (seen.has(key0)) continue;
    const comp = [], ends = [], open = [], anchored = [];
    const stack = [c];
    seen.add(key0);
    while (stack.length) {
      const u = stack.pop();
      comp.push(u);
      const od = openDirs(u);
      if (!(od.includes(u.open[0]) && od.includes(u.open[1]))) errors.push(`cable at ${u.cell} encodes the wrong faces`);
      // anchored (the game's rule): joined to a port, or (flat, on the floor) a straight cell lying on its welded top
      if (L.floor && u.shape === 0 && u.cell[1] === 0 && !od.some((d) => DIRS[d][1] !== 0)) anchored.push(u);
      for (const d of od) {
        const n = vadd(u.cell, DIRS[d]), nk = n.join();
        const v = cab.get(nk);
        if (v) {
          if (openDirs(v).includes(opposite(d))) { if (!seen.has(nk)) { seen.add(nk); stack.push(v); } }
          else errors.push(`cable at ${u.cell} opens onto a closed cable face at ${n}`);
          continue;
        }
        const occ = L.at(n);
        if (occ === -2) { open.push({ cell: u.cell, d }); continue; }
        if (occ >= 0) {
          const hit = (portAt.get(u.cell.join()) || []).find((pp) => pp.i === occ && veq(pp.face, n));
          if (hit) { ends.push(canon(L.parts[occ].id, hit.q.name)); anchored.push(u); }
          else errors.push(`cable at ${u.cell} opens onto a plain face of ${L.parts[occ].id}`);
          continue;
        }
        errors.push(`cable at ${u.cell} has a dangling open face toward ${n}`);
      }
    }
    // every cell within MAX_UNANCHORED steps of an anchored cell along its own cable
    const dist = new Map(anchored.map((u) => [u.cell.join(), 0])), queue = anchored.slice();
    while (queue.length) {
      const u = queue.shift(), du = dist.get(u.cell.join());
      for (const d of openDirs(u)) {
        const v = cab.get(vadd(u.cell, DIRS[d]).join());
        if (v && !dist.has(v.cell.join())) { dist.set(v.cell.join(), du + 1); queue.push(v); }
      }
    }
    const far = comp.filter((u) => !(dist.get(u.cell.join()) <= MAX_UNANCHORED));
    if (far.length) errors.push(`cable at ${far[0].cell}: ${far.length} cells more than ${MAX_UNANCHORED} from an anchor`);
    for (const dd of dist.values()) if (dd > farthest) farthest = dd;
    found.push({ ends: ends.sort(), open, cells: comp.length });
  }
  // direct port contacts
  const contactSet = new Set();
  L.parts.forEach((p, i) => {
    for (const q of L.geo(i).portList) {
      const cell = vadd(p.o, q.cell), occ = L.at(cell);
      if (occ < 0 || occ <= i) continue;
      const og = L.geo(occ), oo = L.parts[occ].o;
      for (const r of og.portList) {
        if (veq(vadd(oo, r.face), cell) && veq(vadd(oo, r.cell), vadd(p.o, q.face))) contactSet.add([canon(p.id, q.name), canon(L.parts[occ].id, r.name)].sort().join(' '));
      }
    }
  });
  const contacts = [...contactSet].map((k) => k.split(' '));
  // compare with what the circuit asks for
  const want = new Map();
  L.nets.forEach((n) => want.set([canon(n.a.id, n.a.port), canon(n.b.id, n.b.port)].sort().join(' '), 'net'));
  const got = new Map();
  for (const f of found) {
    if (f.open.length) {
      const st = L.stubs.find((s) => canon(s.end.id, s.end.port) === f.ends[0]);
      const face = f.open[0].d === 5 && f.open[0].cell[2] === 0 ? '-z' : f.open[0].d === 4 && f.open[0].cell[2] === Z - 1 ? '+z' : '?';
      if (f.ends.length !== 1 || f.open.length !== 1 || !st || st.face !== face) errors.push(`bad stub: ends ${f.ends.join(',')} open ${JSON.stringify(f.open)}`);
      const li = st ? L.stubLabel[L.stubs.indexOf(st)] : -1;
      if (li >= 0 && f.open.length) {
        const lp = L.parts[li], e = f.open[0].cell;
        const beside = L.geo(li).cells.some((c) => { const w = vadd(lp.o, c); return Math.abs(w[0] - e[0]) + Math.abs(w[1] - e[1]) + Math.abs(w[2] - e[2]) === 1; });
        if (!beside) errors.push(`stub ${st.label} does not end beside its label`);
      }
      continue;
    }
    if (f.ends.length !== 2) { errors.push(`cable network joins ${f.ends.length} ports: ${f.ends.join(', ')}`); continue; }
    got.set(f.ends.join(' '), (got.get(f.ends.join(' ')) || 0) + 1);
  }
  for (const c of contacts) got.set(c.join(' '), (got.get(c.join(' ')) || 0) + 1);
  for (const [k] of want) if (!got.has(k)) errors.push(`missing connection ${k}`);
  for (const [k, n] of got) {
    if (!want.has(k)) errors.push(`unintended connection ${k}`);
    else if (n > 1) errors.push(`connection made ${n} times: ${k}`);
  }
  // labels lying on a flat floor, and parts standing on it, are held by the floor
  L.parts.forEach((p, i) => {
    if (!p.label || L.flat) return;
    const back = [0, 0, p.label.back], cells = L.geo(i).cells;
    const loose = cells.filter((c) => { const occ = L.at(vadd(vadd(p.o, c), back)); return occ < 0 || L.isLabel[occ]; }).length;
    if (p.label.bus !== undefined ? 2 * loose > cells.length : loose > 0) errors.push(`label "${p.label.text}" is not backed by a part`);
  });
  const comps = L.flat ? 1 : L.components();
  if (comps > 1) errors.push(`parts form ${comps} separate groups (each must touch the rest)`);
  return { errors, contacts: contacts.length, networks: found.length, farthest };
}

// ---------- labels ----------
// Upper case, and only the characters the game's own labels use (A-Z 0-9 space % + , - . / :).
function labelText(s) {
  return String(s).toUpperCase().replace(/[^A-Z0-9%+,\-./: ]+/g, ' ').replace(/\s+/g, ' ').trim()
    .slice(0, D.parts.label_large.max_chars);
}

// ---------- settings ----------
const COND_MODE = [0, 1, 2, 4, 3, 5];          // engine op (aupbuilder 0 =,1 ≠,2 <,3 >,4 ≤,5 ≥) -> game _mode
const ROUND_MODE = [1, 0, 2];                  // engine 0 round,1 floor,2 ceil -> game 0 floor,1 round,2 ceil
const DIFF_INTERVALS = [1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60];
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
function settingsFor(type, prm, label) {
  const p = prm || {};
  const num = (v, d) => (typeof v === 'number' && Number.isFinite(v) ? v : d);
  switch (type) {
    case 'constant': return { _value: ['f32', num(p.value, 0)] };
    case 'simple_threshold': return { _value: ['f32', num(p.threshold, 0.5)] };
    case 'condition': return { _mode: ['u8', COND_MODE[num(p.op, 0)] ?? 0] };
    case 'round': return { _mode: ['u8', ROUND_MODE[num(p.mode, 0)] ?? 1] };
    case 'memory': case 'accumulator': return { _mode: ['u8', num(p.mode, 0) ? 1 : 0] };
    case 'delay': return { _rotKnobValue: ['f32', (clamp(Math.round(num(p.ticks, 1)), 1, 60) - 0.5) / 60] };
    case 'differentiator': {
      const want = num(p.interval, 1);
      const i = DIFF_INTERVALS.reduce((b, v, k) => (Math.abs(v - want) < Math.abs(DIFF_INTERVALS[b] - want) ? k : b), 0);
      return { _rotKnobValue: ['f32', (i + 0.5) / 12] };
    }
    case 'initializer': return { _ticks: ['u16', clamp(Math.round(num(p.ticks, 0)), 0, 59)] };
    case 'remapper': return { _value0: ['f32', num(p.in_min, 0)], _value1: ['f32', num(p.in_max, 1)],
      _value2: ['f32', num(p.out_min, 0)], _value3: ['f32', num(p.out_max, 1)] };
    case 'fader': return { _lever: ['f32', clamp(num(p.value, 1), 0, 1)] };
    case 'datameter': return { _inputSwitch: ['u8', 0], _actionableLabel: ['text', label], _labelRotated: ['u8', 0] };
    case 'wireless_transmitter': return { _channel: ['i32', num(p.channel, 0)], _actionableLabel: ['text', label], _labelRotated: ['u8', 0] };
    default: return {};
  }
}

// ---------- .bp writer ----------
const SCHEMA = D.schema;
const STRUCT_INDEX = new Map(SCHEMA.map((s, i) => [s.name, i]));
function hexToBytesLE(hex) {
  const out = new Uint8Array(8);
  for (let i = 0; i < 8; i++) out[i] = parseInt(hex.slice(14 - 2 * i, 16 - 2 * i), 16);
  return out;
}
function randomGuid(rng) {
  const b = new Uint8Array(16);
  if (rng) for (let i = 0; i < 16; i++) b[i] = Math.floor(rng() * 256);
  else if (typeof crypto !== 'undefined' && crypto.getRandomValues) crypto.getRandomValues(b);
  else b.set(require('crypto').randomBytes(16));
  b[7] = (b[7] & 0x0f) | 0x40;                   // .NET byte order: version nibble lives in byte 7
  b[8] = (b[8] & 0x3f) | 0x80;
  return b;
}
function guidString(b) {
  const h = [...b].map((x) => x.toString(16).padStart(2, '0'));
  const le = (a) => a.slice().reverse().join('');
  return `${le(h.slice(0, 4))}-${le(h.slice(4, 6))}-${le(h.slice(6, 8))}-${h.slice(8, 10).join('')}-${h.slice(10).join('')}`;
}
function packCell(c, k) { return c[0] + c[1] * 512 + c[2] * 262144 + k * 134217728; }

function structBytes(structName, values) {
  const st = SCHEMA[STRUCT_INDEX.get(structName)];
  const buf = new Uint8Array(st.size), dv = new DataView(buf.buffer);
  const fields = new Map(st.fields.map(([name, , off]) => [name, off]));
  for (const [name, [kind, v]] of Object.entries(values)) {
    if (!fields.has(name)) continue;
    const off = fields.get(name);
    switch (kind) {
      case 'guid': buf.set(v, off); break;
      case 'u32': dv.setUint32(off, v >>> 0, true); break;
      case 'i32': dv.setInt32(off, v | 0, true); break;
      case 'u16': dv.setUint16(off, v, true); break;
      case 'u8': buf[off] = v & 255; break;
      case 'f32': dv.setFloat32(off, v, true); break;
      case 'text': { const s = String(v || '').slice(0, 16); for (let i = 0; i < s.length; i++) dv.setUint16(off + 2 * i, s.charCodeAt(i), true); break; }
      default: throw new Error(`unknown field kind ${kind}`);
    }
  }
  return buf;
}

function writeBp(records) {
  let size = 4;
  for (const s of SCHEMA) size += 16 + 16 * s.fields.length;
  for (const r of records) size += 16 + r.bytes.length;
  const out = new Uint8Array(size), dv = new DataView(out.buffer);
  let o = 0;
  dv.setUint32(o, SCHEMA.length, true); o += 4;
  for (const s of SCHEMA) {
    out.set(hexToBytesLE(s.hash), o); dv.setUint32(o + 8, s.size, true); dv.setUint32(o + 12, s.fields.length, true); o += 16;
    for (const [, hash, off, sz] of s.fields) { out.set(hexToBytesLE(hash), o); dv.setUint32(o + 8, off, true); dv.setUint32(o + 12, sz, true); o += 16; }
  }
  for (const r of records) {
    out.set(hexToBytesLE(r.hash), o); dv.setUint32(o + 8, STRUCT_INDEX.get(r.struct), true); dv.setUint32(o + 12, 0, true); o += 16;
    out.set(r.bytes, o); o += r.bytes.length;
  }
  return out;
}

// ---------- the whole pipeline ----------
function levels(parts, nets) {
  const idx = new Map(parts.map((p, i) => [p.id, i]));
  const lv = new Array(parts.length).fill(0);
  for (let pass = 0; pass < parts.length; pass++) {        // longest path, feedback edges capped by the pass limit
    let changed = false;
    for (const n of nets) {
      const a = idx.get(n.a.id), b = idx.get(n.b.id);
      if (lv[b] < lv[a] + 1 && lv[a] + 1 < parts.length) { lv[b] = lv[a] + 1; changed = true; }
    }
    if (!changed) break;
  }
  return lv;
}

// A flat layout's box is two cells high: the parts' layer, and the level above it for cables.
const FLAT_Y = 2;
// The floor under a flat layout: Frame Quarters (tools/bp/parts/structure.json: 4x4x4, 11 kg, canonical orientation
// 16 = identity; face bits 0 Y-, 1 Y+, 2 X+, 3 Z+, 4 X-, 5 Z-; _col 200 = unpainted) with the top face welded. A welded
// face anchors every straight cable cell lying on it (tools/bp/parts/power.md, Q4), so on the floor a cable's reach
// is no longer limited to 10 cells from a port.
const FLOOR_FRAME = { hash: '482074ef572f3723', struct: 'EPC_SCFrame', k: 16, solid: 1 << 1 };
const FLOOR_REACH = 200;
const MAX_UNANCHORED = 10;                       // the game's MAX_UNANCHORED_CELLS

function candidateBoxes(volume, heights = [2, 3, 4, 6, 8]) {
  // cube-aligned boxes (multiples of 4 cells), fewest cubes first, then the least volume
  const out = [];
  for (const Y of heights) {
    const cy = Math.ceil(Y / 4);
    for (let cx = 1; cx <= 12; cx++) for (let cz = 1; cz <= 12; cz++) {
      const X = cx * 4, Z = cz * 4;
      if (X * Y * Z < volume) continue;
      out.push({ box: [X, Y, Z], cubes: cx * cy * cz, vol: X * Y * Z });
    }
  }
  out.sort((a, b) => a.cubes - b.cubes || a.vol - b.vol || a.box[1] - b.box[1]);
  return out;
}

// How the stubs leave the blueprint (opts.io):
//   bundle  every stub ends in one row on the -z face (inputs first, then outputs): one group of parallel cables
//   split   inputs in a row on the -z face, outputs in a row on the +z face
//   free    each stub ends wherever suits it on its face (inputs -z, outputs +z), with its label beside the end
// Without opts.io each box tries bundle, then split; free is the last resort once no box works.
// flat: each label lies face up on the floor beside its end, upright to someone standing at that face.
function ioPlan(nl, mode, maxLevel, labelsOn, flat = false) {
  const stubs = nl.stubs.map((s) => ({ ...s, face: mode === 'bundle' || s.io === 'in' ? '-z' : '+z' }));
  const buses = [];
  if (mode !== 'free') {
    for (const face of ['-z', '+z']) {
      const members = stubs.map((_, si) => si).filter((si) => stubs[si].face === face);
      members.sort((a, b) => (stubs[a].io === 'in' ? 0 : 1) - (stubs[b].io === 'in' ? 0 : 1) || a - b);
      if (members.length) { members.forEach((si) => { stubs[si].bus = buses.length; }); buses.push({ face, members, x0: 0, y0: 0 }); }
    }
  }
  // a Label (Large Label if the name needs it) for every stub, facing out of its face. Its text reads toward +x on
  // the -z face and toward -x on the +z face; a bus end sits under the label's first letter (flat: just before it).
  const labels = !labelsOn ? [] : stubs.map((s, si) => {
    const text = labelText(s.label);
    const type = text.length <= D.parts.label_small.max_chars ? 'label_small' : 'label_large';
    const w = D.parts[type].size[0], minus = s.face === '-z';
    return { id: `label#${si}`, type, params: {}, level: maxLevel + 1,
      label: { stub: si, io: s.io, text, back: minus ? 1 : -1, bus: s.bus, w, exitDx: flat ? (minus ? -1 : w) : (minus ? 0 : w - 1) },
      vars: [{ k: flat ? LYING[minus ? 0 : 1] : UPRIGHT[minus ? 5 : 4], mir: false, upright: true }], v: 0, o: [0, 0, 0] };
  });
  return { mode, stubs, buses, labels };
}

// The cells a part needs: its volume, or for a flat layout the floor it covers standing upright times the box's
// height (so flat boxes compare by floor area).
const partCells = (type, flat) => { const s = D.parts[type].size; return flat ? s[0] * FLAT_Y * s[2] : s[0] * s[1] * s[2]; };
const labelType = (label) => (labelText(label).length <= D.parts.label_small.max_chars ? 'label_small' : 'label_large');

// Flat boxes: a flat layout's I/O rows (each end beside its lying label) set its least width, and its parts' area plus
// some floor for each cable its least depth, so per depth only the two narrowest widths that hold both are worth
// trying.
function flatBoxes(nl, opts, area) {
  const slot = (ss) => ss.reduce((w, s) => w + D.parts[labelType(s.label)].size[0] + 1, 0);
  const ins = nl.stubs.filter((s) => s.io === 'in'), outs = nl.stubs.filter((s) => s.io === 'out');
  const rows = opts.labels === false ? 1 : opts.io === 'bundle' ? slot(nl.stubs) : Math.max(slot(ins), slot(outs), 1);
  const need = Math.ceil(area + 4 * (nl.nets.length + nl.stubs.length)), out = [];
  for (let cz = 1; cz <= 12; cz++) {
    const cx0 = Math.ceil(Math.max(rows, need / (4 * cz)) / 4);
    for (let cx = cx0; cx <= Math.min(12, cx0 + 1); cx++) out.push({ box: [4 * cx, FLAT_Y, 4 * cz], cubes: cx * cz, vol: 16 * cx * cz * FLAT_Y });
  }
  out.sort((a, b) => a.cubes - b.cubes || a.vol - b.vol);
  return out;
}

// The boxes generate() would try for this circuit, smallest first (for a caller that searches them in parallel).
function searchBoxes(circuit, opts = {}) {
  const nl = netlist(circuit, opts), flat = !!opts.flat;
  let vol = nl.included.reduce((s, i) => s + partCells(i.type_id, flat), 0);
  if (opts.labels !== false) for (const s of nl.stubs) vol += partCells(labelType(s.label), flat);
  const boxes = flat ? flatBoxes(nl, opts, vol / FLAT_Y) : candidateBoxes(Math.ceil(vol * (opts.slack || 2.2)));
  boxes.partVolume = vol;
  return boxes;
}

// opts.flat lays the parts out in one layer (see Layout) on a floor of Frame Quarters: every part upright on the
// floor, none on another, each label lying beside its end; cables may run one level up. opts.floor = false leaves the
// floor out, for pasting onto a floor of your own (cable reach is then counted from the ports only, as elsewhere).
function generate(circuit, opts = {}) {
  const t0 = Date.now();
  const rng = mulberry32(opts.seed ?? 1);
  const nl = netlist(circuit, opts);
  if (!nl.included.length) throw new Error('nothing to place: the circuit has no logic parts');
  const flat = !!opts.flat, floor = flat && opts.floor !== false;
  const proto = nl.included.map((i) => ({ id: i.id, type: i.type_id, params: i.parameters || {},
    vars: variantsFor(i.type_id, !flat && opts.allOrientations !== false), v: 0, o: [0, 0, 0] }));
  const lv = levels(proto, nl.nets);
  const maxLevel = Math.max(...lv);
  proto.forEach((p, i) => { p.level = lv[i]; });
  const labelsOn = opts.labels !== false;
  const modes = opts.io ? [opts.io] : labelsOn ? ['bundle', 'split'] : ['free'];
  const plans = modes.map((m) => ioPlan(nl, m, maxLevel, labelsOn, flat));
  const fallback = !opts.io && labelsOn ? ioPlan(nl, 'free', maxLevel, true, flat) : null;
  const volumeOf = (ps) => ps.reduce((s, p) => s + partCells(p.type, flat), 0);
  const partVolume = volumeOf(proto) + volumeOf(plans[0].labels);
  const slack = opts.slack || 2.2;
  const given = opts.box && (flat ? [opts.box[0], FLAT_Y, opts.box[2]] : opts.box);
  const boxes = given ? [{ box: given, cubes: given.reduce((n, d) => n * Math.ceil(d / 4), 1), vol: given[0] * given[1] * given[2] }]
    : flat ? flatBoxes(nl, opts, partVolume / FLAT_Y) : candidateBoxes(Math.ceil(partVolume * slack));
  const attempts = [];
  const note = (a) => { attempts.push(a); if (opts.onProgress) opts.onProgress(`${a.box.join('x')} ${a.io}: ${a.why}`); };
  const budget = opts.timeBudgetMs || 60000;
  const attempt = (cand, plan) => {
    for (let tryNo = 0; tryNo < (opts.triesPerBox || 1); tryNo++) {
      const parts = proto.concat(plan.labels).map((p) => ({ ...p, o: p.o.slice() }));
      const buses = plan.buses.map((b) => ({ face: b.face, members: b.members.slice(), x0: 0, y0: 0, down: new Set() }));
      const L = new Layout(parts, nl.nets, plan.stubs, cand.box, buses,
        { flat, floor, maxNet: floor ? FLOOR_REACH : undefined, maxStub: floor ? FLOOR_REACH : undefined });
      L.maxLevel = maxLevel;
      const why = (w) => note({ box: cand.box, io: plan.mode, why: w });
      if (!initialPlacement(L, rng)) { why(plan.buses.length ? 'parts or I/O row do not fit' : 'parts do not fit'); return null; }
      const steps = opts.steps || Math.max(30000, 2500 * parts.length);
      anneal(L, rng, steps);
      let ev = L.evaluate(true);
      if (ev.problems.length || ev.components > 1) { why(`placement: ${ev.problems[0] || `${ev.components} groups`}`); continue; }
      let freeCells = 0;
      for (let c = 0; c < L.grid.length; c++) if (L.grid[c] === -1) freeCells++;
      if (ev.wire > 0.85 * freeCells) { why(`too dense: ~${ev.wire} cable cells for ${freeCells} free cells`); return null; }
      let routed = route(L, ev.direct, opts);
      // routing repair: push parts off the cells where the cables ran out of room, then route again
      // (flat: once; there more rounds hardly ever clear it)
      for (let rep = 0; !routed.ok && routed.hot && rep < (opts.repairs ?? (flat ? 1 : 4)); rep++) {
        L.markHot(routed.hot, 5);
        anneal(L, rng, Math.round(steps / 4), { T0: 3, T1: 0.1 });
        ev = L.evaluate(true);
        if (ev.problems.length || ev.components > 1) break;
        routed = route(L, ev.direct, opts);
      }
      if (ev.problems.length || ev.components > 1) { why(`placement (repair): ${ev.problems[0] || `${ev.components} groups`}`); continue; }
      if (!routed.ok) { why(`routing: ${routed.reason || `${routed.tooLong} cables over the reach limit`}`); continue; }
      const cables = cablesFrom(L, routed);
      const chk = check(L, cables);
      if (chk.errors.length) { why(`check: ${chk.errors[0]}`); continue; }
      if (opts.onProgress) opts.onProgress(`${cand.box.join('x')} ${plan.mode}: placed and routed`);
      return { L, ev, routed, cables, chk, box: cand.box, cubes: cand.cubes, io: plan.mode };
    }
    return null;
  };
  let result = null;
  for (const cand of boxes) {
    if (Date.now() - t0 > budget) break;
    for (const plan of plans) { result = attempt(cand, plan); if (result || Date.now() - t0 > budget) break; }
    if (result) break;
  }
  if (!result && fallback) {
    for (const cand of boxes) { if (Date.now() - t0 > budget * 1.5) break; if ((result = attempt(cand, fallback))) break; }
  }
  if (!result) {
    const e = new Error('no layout found'); e.attempts = attempts; throw e;
  }
  return finish(result, nl, circuit, opts, attempts, Date.now() - t0);
}

function finish(res, nl, circuit, opts, attempts, ms) {
  const { L, cables } = res;
  // trim the empty margin: the blueprint is the bounding box of what was placed; stubs still end on its z faces
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  const grow = (c) => { for (let a = 0; a < 3; a++) { lo[a] = Math.min(lo[a], c[a]); hi[a] = Math.max(hi[a], c[a]); } };
  L.parts.forEach((p, i) => { for (const c of L.geo(i).cells) grow(vadd(p.o, c)); });
  cables.forEach((c) => grow(c.cell));
  if (L.stubs.some((s) => s.face === '-z')) lo[2] = 0;
  if (L.stubs.some((s) => s.face === '+z')) hi[2] = L.box[2] - 1;
  const size = [0, 1, 2].map((a) => hi[a] - lo[a] + 1);
  // flat: the floor is a layer of Frame Quarters under the circuit's footprint, so the circuit's low corner goes on
  // the game's 4-cell frame grid
  const floorQ = L.floor ? [Math.ceil(size[0] / 4), Math.ceil(size[2] / 4)] : null;
  const cubes = size.reduce((n, d) => n * Math.ceil(d / 4), 1);  // the circuit's own; the floor is reported apart
  const grid4 = (v) => Math.floor(v / 4) * 4;
  const base = vsub(L.flat ? (opts.base || [240, 252, 240]).map(grid4) : (opts.base || [240, 250, 240]), lo);
  const paint = opts.paint !== false;
  const records = [];
  const guidRng = opts.deterministic ? mulberry32((opts.seed ?? 1) * 7919) : null;
  if (floorQ) {
    for (let qx = 0; qx < floorQ[0]; qx++) for (let qz = 0; qz < floorQ[1]; qz++) {
      const cell = vadd(vadd(base, lo), [4 * qx, -4, 4 * qz]);
      const values = { _guid: ['guid', randomGuid(guidRng)], _gt: ['u32', packCell(cell, FLOOR_FRAME.k)], _solidFaces: ['u8', FLOOR_FRAME.solid] };
      for (let f = 0; f < 8; f++) values[`_col${f}`] = ['u8', 200];
      records.push({ hash: FLOOR_FRAME.hash, struct: FLOOR_FRAME.struct, bytes: structBytes(FLOOR_FRAME.struct, values) });
    }
  }
  for (const p of L.parts) {
    const P = D.parts[p.type], v = p.vars[p.v];
    if (p.label) {
      const values = { _guid: ['guid', randomGuid(guidRng)], _gt: ['u32', packCell(vadd(base, p.o), v.k)],
        _col: ['u8', paint ? PAINT[CABLE_PAINT[p.label.io]] : 0], _actionableLabel: ['text', p.label.text], _labelRotated: ['u8', 0] };
      records.push({ hash: P.hash, struct: P.struct, bytes: structBytes(P.struct, values) });
      continue;
    }
    const col = paint ? PAINT[PART_COLOR] : 0;
    const values = { _guid: ['guid', randomGuid(guidRng)], _gt: ['u32', packCell(vadd(base, p.o), v.k)], _col: ['u8', col],
      ...settingsFor(p.type, p.params, p.id) };
    records.push({ hash: v.mir ? P.mirrored_hash : P.hash, struct: P.struct, bytes: structBytes(P.struct, values) });
  }
  const accent = new Map();                       // job -> stripe colour, in routing order
  for (const c of cables) {
    if (c.role === 'net' && !accent.has(c.job)) accent.set(c.job, NET_ACCENTS[accent.size % NET_ACCENTS.length]);
    let col = 0;
    if (paint) col = PAINT[c.role === 'net' && opts.stripes === true && c.step % 2 === 0 ? accent.get(c.job) : CABLE_PAINT[c.role]];
    const values = { _guid: ['guid', randomGuid(guidRng)], _gt: ['u32', packCell(vadd(base, c.cell), c.k)],
      _shape: ['u8', c.shape], _type: ['u8', D.cable.type_byte], _col: ['u8', col] };
    records.push({ hash: D.cable.hash, struct: D.cable.struct, bytes: structBytes(D.cable.struct, values) });
  }
  const bp = writeBp(records);
  const name = (opts.name || circuit.name || 'au-sim circuit').slice(0, 60);
  const meta = JSON.stringify({ _name: name, _folder: opts.folder ?? 'au-sim', _version: D.version });
  const directs = res.ev.direct.filter(Boolean).length;
  const report = {
    name, box: size, frameQuarters: cubes, searchBox: res.box, parts: L.parts.filter((p) => !p.label).length,
    labels: L.parts.filter((p) => p.label).length, cableCells: cables.length,
    nets: L.nets.length, directContacts: directs, cabledNets: L.nets.length - directs,
    io: res.io, flat: L.flat,
    // flat: the floor's Frame Quarters (x by z) under the circuit, and the cable cells one level up
    floor: floorQ, raisedCables: L.flat ? cables.filter((c) => c.cell[1] > 0).length : 0,
    buses: L.buses.map((b) => ({ face: b.face, rows: b.rows, ends: b.members.map((si) => L.stubs[si].label) })),
    stubs: L.stubs.map((s, si) => ({ label: s.label, io: s.io, face: s.face, port: `${s.end.id}.${s.end.port}`,
      text: L.stubLabel[si] >= 0 ? L.parts[L.stubLabel[si]].label.text : null })),
    substituted: nl.substituted, longestCable: Math.max(0, ...res.routed.paths.map((p) => p.length)),
    routingIterations: res.routed.iterations, attempts, ms,
  };
  return { bp, meta, name, guid: guidString(randomGuid(guidRng)), report, layout: { origin: lo, parts: L.parts.map((p) => ({ id: p.id, type: p.type, o: vsub(p.o, lo), k: p.vars[p.v].k, mir: p.vars[p.v].mir })), cables: cables.map((c) => ({ ...c, cell: vsub(c.cell, lo) })) } };
}

const api = { generate, searchBoxes, netlist, geometry, settingsFor, writeBp, structBytes, PAINT, CABLE_PAINT, UPRIGHT, LYING, CORNER, STRAIGHT,
  _internal: { Layout, anneal, route, initialPlacement, levels, variantsFor, check, cablesFrom, mulberry32, ioPlan, portOnCell } };
if (typeof module !== 'undefined') module.exports = api;
else root.BPGEN = api;
})(typeof window !== 'undefined' ? window : globalThis);
