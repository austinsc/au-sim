"""Network-level test of the cable anchoring rule with the frames' real face polygons (FaceSetupData).

    python structure_anchor.py        # writes structure_anchor_stats.json

Rule under test (Burst GarageUpdateCables.UpdateCellsAndPortsJob; read in the power study and re-read here):
  1. a cable cell joined to a compatible port is anchored;
  2. a STRAIGHT cable cell (shape 0) probes the 4 directions perpendicular to its axis. When the neighbour cell in
     that direction belongs to a frame, the line through the cable cell centre along the probe is intersected with
     the frame's face polygons in index order (Moller-Trumbore, triangles (v0,v1,v2) and for quads (v0,v2,v3),
     back faces culled: only a face whose outward normal points against the probe counts). The first face hit
     decides: anchored if its _solidFaces bit is set (and, on a frame with ports, the probe is not at a port), or
     if the hit point is within 0.08 m of the LINE through any edge of that polygon;
  3. every cell needs an anchored cell within 10 steps along its own cable chain.
Models compared (networks with a cell > 10 steps from every anchor; fewer = better fit):
  ports      ports only
  edges      + frame edge rule, welds ignored
  exact      + welded faces, bit = FaceSetupData index (this study)
  joints     + welded faces, bit = JointsArea child order XP XM YP YM ZP ZM (box frames only; earlier guess)
  anyside    + any straight cell whose side touches a frame (upper bound)
"""
import collections, json, math, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import structure_corpus as sc  # noqa: E402
import structure_geom as g  # noqa: E402
import structure_occupancy as so  # noqa: E402
import structure_prefabs as sp  # noqa: E402

CELL = 0.125
OPEN = {0: ((0, 0, 1), (0, 0, -1)), 1: ((0, 1, 0), (0, 0, 1))}
FACE_DIR = {0: (1, 0, 0), 1: (-1, 0, 0), 2: (0, 1, 0), 3: (0, -1, 0), 4: (0, 0, 1), 5: (0, 0, -1)}
COMPAT = {'SC_DataCable': {0, 1, 3, 5}, 'SC_PowerCable': {2, 5}, 'SC_PlasmaCable': {4, 5}}
MAXD = 10
JOINT_ORDER = ['X+', 'X-', 'Y+', 'Y-', 'Z+', 'Z-']

# ---------------------------------------------------------------- ports of every prefab (canonical)
_PORTS = {}


def prefab_ports(prefab):
    """[(port cell, face cell, type code or None)] canonical, from the root component's port list (20-byte entries:
    position f32[3], face code u32, type u32); falls back to the Port renderers (type None = any cable)."""
    if prefab in _PORTS:
        return _PORTS[prefab]
    t, b = sp.root_component(prefab)
    size = sp.size_cells(prefab)
    out = []
    rend = sp.ports(prefab)
    found = False
    if rend and b:
        pos = [v['pos_m'] for v in rend.values()]
        for o in range(0, len(b) - 4, 4):
            cnt = struct.unpack_from('<I', b, o)[0]
            if cnt != len(pos):
                continue
            ents = []
            for i in range(cnt):
                e = o + 4 + 20 * i
                if e + 20 > len(b):
                    break
                p = struct.unpack_from('<3f', b, e)
                fc, typ = struct.unpack_from('<2I', b, e + 12)
                if not any(all(abs(q[j] - p[j]) < 1e-3 for j in range(3)) for q in pos) or fc > 5:
                    break
                ents.append((p, fc, typ))
            if len(ents) == cnt:
                for p, fc, typ in ents:
                    face = sp.pos_to_cell(p, size)
                    d = FACE_DIR[fc]
                    out.append((tuple(face[i] + d[i] for i in range(3)), tuple(face), typ))
                found = True
                break
    if not found:
        for v in rend.values():
            out.append((tuple(v['cell']), tuple(v['face']), None))
    _PORTS[prefab] = out
    return out


# ---------------------------------------------------------------- frame faces (canonical cell units)
_FACES = {}


def frame_faces(prefab, mirrored):
    key = (prefab, mirrored)
    if key not in _FACES:
        size = sp.size_cells(prefab)
        faces = []
        for i, f in enumerate(sp.frame_faces(prefab) or []):
            pts = []
            for v in f['verts']:
                q = [v[a] / CELL + size[a] / 2 for a in range(3)]
                if mirrored:
                    q[0] = size[0] - q[0]
                pts.append(tuple(q))
            if mirrored:
                pts = pts[::-1]          # reflection flips the winding; keep normals outward
            faces.append((i, f['label'], pts))
        _FACES[key] = faces
    return _FACES[key]


def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def mt(orig, d, v0, v1, v2):
    e1, e2 = sub(v1, v0), sub(v2, v0)
    pv = cross(d, e2)
    det = dot(e1, pv)
    if det < 1e-8:
        return None                     # back face (or parallel): culled
    inv = 1.0 / det
    tv = sub(orig, v0)
    u = dot(tv, pv) * inv
    if u < 0 or u > 1:
        return None
    qv = cross(tv, e1)
    v = dot(d, qv) * inv
    if v < 0 or u + v > 1:
        return None
    t = dot(e2, qv) * inv
    return t


def probe(prefab, mirrored, orig, d):
    """First face (index order) the line hits -> (index, label, min distance in m to the polygon's edge lines)."""
    for i, label, P in frame_faces(prefab, mirrored):
        t = mt(orig, d, P[0], P[1], P[2])
        if t is None and len(P) == 4:
            t = mt(orig, d, P[0], P[2], P[3])
        if t is None:
            continue
        hit = (orig[0] + t * d[0], orig[1] + t * d[1], orig[2] + t * d[2])
        best = 1e9
        for k in range(len(P)):
            a, b = P[k], P[(k + 1) % len(P)]
            ab = sub(b, a)
            L = math.sqrt(dot(ab, ab))
            if L == 0:
                continue
            c = cross(sub(hit, a), (ab[0] / L, ab[1] / L, ab[2] / L))
            best = min(best, math.sqrt(dot(c, c)) * CELL)
        return i, label, best
    return None


# ---------------------------------------------------------------- per blueprint
def analyse(bp, placed, occ):
    cab = {}
    for P in placed:
        if P['cat'] == 'cable':
            cab[P['origin']] = P
    opens = {c: {g.dir_world(P['rot'], o) for o in OPEN.get(P['rec']['data'][20], ())} for c, P in cab.items()}
    adj = {c: [] for c in cab}
    for c in cab:
        for d in opens[c]:
            n = (c[0] + d[0], c[1] + d[1], c[2] + d[2])
            if n in cab and cab[n]['prefab'] == cab[c]['prefab'] and (-d[0], -d[1], -d[2]) in opens[n]:
                adj[c].append(n)
    # port anchors
    port_anch = set()
    for P in placed:
        if P['cat'] == 'cable':
            continue
        for pc, fc, typ in prefab_ports(P['prefab']):
            if P['mirrored']:
                w = P['size'][0]
                pc, fc = (w - 1 - pc[0], pc[1], pc[2]), (w - 1 - fc[0], fc[1], fc[2])
            wc = g.to_world(P['size'], P['origin'], P['rot'], pc)
            wf = g.to_world(P['size'], P['origin'], P['rot'], fc)
            if wc in cab and sub(wf, wc) in opens[wc]:
                if typ is None or typ in COMPAT[cab[wc]['prefab']]:
                    port_anch.add(wc)
    # frame anchors
    anch = {m: set(port_anch) for m in ('ports', 'edges', 'exact', 'joints', 'anyside')}
    contact_log = collections.Counter()
    for c, C in cab.items():
        if C['rec']['data'][20] != 0:
            continue
        axis = g.dir_world(C['rot'], (0, 0, 1))
        for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
            if dot(d, axis) != 0:
                continue
            q = (c[0] + d[0], c[1] + d[1], c[2] + d[2])
            for j in occ.get(q, []):
                F = placed[j]
                if F['cat'] != 'frame':
                    continue
                sf = sc.field(F['rec'], '_solidFaces')
                if sf is None:
                    continue
                anch['anyside'].add(c)
                faces = frame_faces(F['prefab'], F['mirrored'])
                if not faces:
                    continue
                lc = g.to_local(F['size'], F['origin'], F['rot'], c)
                if F['mirrored']:
                    pass                     # to_local gives the twin's own canonical frame; faces were mirrored
                orig = (lc[0] + 0.5, lc[1] + 0.5, lc[2] + 0.5)
                dl = g.rot(g.inv(g.ORI[F['rot']]), d)
                hit = probe(F['prefab'], F['mirrored'], orig, dl)
                if hit is None:
                    contact_log['no_face_hit'] += 1
                    continue
                fi, label, dist = hit
                edge = dist < 0.08
                welded = (sf[0] >> fi) & 1
                if F['prefab'].startswith('SC_FrameQuarterPorts') and welded:
                    # the weld does not count where a port collider is: probe cell = a port face cell
                    pcs = {fc for pc, fc, typ in prefab_ports(F['prefab'])}
                    ql = g.to_local(F['size'], F['origin'], F['rot'], q)
                    if F['mirrored']:
                        ql = (F['size'][0] - 1 - ql[0], ql[1], ql[2])
                    if ql in pcs:
                        welded = 0
                contact_log[('edge' if edge else 'inner', 'welded' if welded else 'open')] += 1
                if edge:
                    anch['edges'].add(c)
                    anch['exact'].add(c)
                    anch['joints'].add(c)
                if welded:
                    anch['exact'].add(c)
                if label in JOINT_ORDER and (sf[0] >> JOINT_ORDER.index(label)) & 1:
                    anch['joints'].add(c)
    # reach
    res = {}
    for m, A in anch.items():
        dist = {c: 0 for c in A}
        frontier = list(A)
        for step in range(1, MAXD + 1):
            nxt = []
            for c in frontier:
                for n in adj[c]:
                    if n not in dist:
                        dist[n] = step
                        nxt.append(n)
            frontier = nxt
        bad = {c for c in cab if c not in dist}
        # networks containing a bad cell
        seen = set()
        nbad = 0
        for c in bad:
            if c in seen:
                continue
            nbad += 1
            stack = [c]
            seen.add(c)
            while stack:
                x = stack.pop()
                for n in adj[x]:
                    if n not in seen:
                        seen.add(n)
                        stack.append(n)
        res[m] = (len(A), len(bad), nbad)
    return res, contact_log


def main():
    tot = collections.defaultdict(lambda: [0, 0, 0, 0])
    log = collections.Counter()
    per_bp = {}
    for bp, placed, occ in so.iter_blueprints():
        res, cl = analyse(bp, placed, occ)
        log.update(cl)
        for m, (na, nb, nn) in res.items():
            t = tot[m]
            t[0] += na
            t[1] += nb
            t[2] += nn
            t[3] += 1 if nn else 0
        per_bp[(bp['name'] or '') + ' | ' + os.path.basename(bp['file'])] = {m: res[m][2] for m in res}
    out = {'models': {m: {'anchored_cells': v[0], 'unanchored_cells': v[1], 'networks_with_unanchored_cells': v[2],
                          'blueprints_affected': v[3]} for m, v in tot.items()},
           'contacts': {f'{k[0]}/{k[1]}' if isinstance(k, tuple) else k: v for k, v in log.items()},
           'blueprints_where_exact_differs_from_anyside': {k: v for k, v in per_bp.items() if v['exact'] != v['anyside']}}
    json.dump(out, open(os.path.join(HERE, 'structure_anchor_stats.json'), 'w'), indent=1)
    for m, v in out['models'].items():
        print(m, v)
    print(out['contacts'])


if __name__ == '__main__':
    main()
