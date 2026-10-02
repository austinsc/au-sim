"""Corpus test of the game's cable-anchoring rule with real frame faces (see power.md, "Reach").

    python power_anchor.py

Game rule (GarageUpdateCables.UpdateCellsAndPortsJob / UpdateAnchoringJob, Burst):
  * a cable cell joined to a compatible port is anchored;
  * a STRAIGHT cable cell probes its 4 sides (perpendicular to its axis) 0.0725 m from its centre; if the
    probe point is inside a frame, the line from the cell centre along that side crosses a face polygon of
    the frame (FramePrefabFacesData, <= 8 faces, _solidFaces bit per face). The cell is anchored if that
    face is welded (bit set) or if the crossing point lies within 0.08 m of the polygon's edges;
  * every other cell must be within 10 cable steps of an anchored cell (MAX_UNANCHORED_CELLS).

Here the frame faces are taken to be the frame prefab's plain JointsArea polygons (_type 0), in child
order (XP, XM, YP, YM, ZP, ZM on the box frames), and the crossed face is the NEAR face. Models:
  ports   : port anchors only
  edge    : + frame faces, edge rule only (welds ignored)
  weld    : + welded faces (bit of the near face's index in the record's _solidFaces)
  weldfar : as weld, but reading the bit of the opposite face (to test the face-index convention)
  any     : + any straight cell whose side touches a frame (upper bound)
For each model: networks whose farthest cell is > 10 steps from an anchor.
"""
import collections, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import power_geom as G
import power_world as W

CELL = G.CELL
EDGE = 0.08 / CELL          # edge distance threshold, in cells
_POLY = {}


def frame_faces(prefab, mirrored):
    """[(face index, [vertices in canonical continuous cell coords])] of the plain JointsArea polygons."""
    key = (prefab, mirrored)
    if key not in _POLY:
        src = prefab + ' M' if mirrored and prefab + ' M' in G.DUMP else prefab
        size = G.size_cells(src)
        faces = []
        k = 0
        for name, a, b, vs in G.joint_polys(src):
            if a != 0:
                continue
            pts = []
            for v in vs:
                x, y, z = v
                if mirrored and src == prefab:
                    x = -x
                pts.append((x / CELL + size[0] / 2, y / CELL + size[1] / 2, z / CELL + size[2] / 2))
            faces.append((k, pts))
            k += 1
        _POLY[key] = faces
    return _POLY[key]


def to_world(p, part):
    """canonical continuous point (cell i spans [i, i+1)) -> world continuous point."""
    m, mn = G.frame(part.size, part.rot)
    q = (p[0] - 0.5, p[1] - 0.5, p[2] - 0.5)
    r = G.rot(m, q)
    return tuple(part.origin[a] - mn[a] + 0.5 + r[a] for a in range(3))


def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def crossing(o, d, poly):
    """Line o + t d vs a planar convex polygon -> (t, point) or None (no culling)."""
    n = cross(sub(poly[1], poly[0]), sub(poly[2], poly[0]))
    den = dot(n, d)
    if abs(den) < 1e-9:
        return None
    t = dot(n, sub(poly[0], o)) / den
    p = (o[0] + t * d[0], o[1] + t * d[1], o[2] + t * d[2])
    sgn = 0
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        c = dot(cross(sub(b, a), sub(p, a)), n)
        if abs(c) < 1e-9:
            continue
        s = 1 if c > 0 else -1
        if sgn and s != sgn:
            return None
        sgn = s
    return t, p


def edge_dist(p, poly):
    best = 1e9
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        ab = sub(b, a)
        L = dot(ab, ab) ** 0.5
        best = min(best, (dot(cross(sub(p, a), ab), cross(sub(p, a), ab)) ** 0.5) / L)
    return best


def main():
    models = ('ports', 'edge', 'weld', 'weldfar', 'any')
    viol = {m: collections.Counter() for m in models}
    hist = {m: collections.Counter() for m in models}
    anchored_cells = collections.Counter()
    for f, recs in W.corpus():
        w = W.world(recs, cache=False)
        if not w['cables']:
            continue
        links = W.cable_links(w)
        pl = W.port_links(w)
        comp, nets = W.components(w, links)
        parts = w['parts']
        frame_at = {}
        for p in parts:
            if p.cls in W.FRAME_CLASSES:
                for c in p.foot:
                    frame_at[c] = p
        world_faces = {}
        port_anchor = {c for c, lst in pl.items() if any(x[-1] for x in lst)}
        A = {m: set(port_anchor) for m in models}
        for c, cb in w['cables'].items():
            if cb.shape != 0 or c in port_anchor:
                continue
            o = (c[0] + 0.5, c[1] + 0.5, c[2] + 0.5)
            for d in W.DIRS:
                if d in cb.opens or W.neg(d) in cb.opens:
                    continue
                fp = frame_at.get(W.add(c, d))
                if fp is None:
                    continue
                A['any'].add(c)
                if fp.idx not in world_faces:
                    world_faces[fp.idx] = [(k, [to_world(v, fp) for v in poly]) for k, poly in frame_faces(fp.prefab, fp.mirrored)]
                hits = []
                for k, poly in world_faces[fp.idx]:
                    r = crossing(o, d, poly)
                    if r and r[0] > 0:
                        hits.append((r[0], k, r[1], poly))
                if not hits:
                    continue
                hits.sort()
                t, k, pt, poly = hits[0]                 # near face
                far = hits[-1][1] if len(hits) > 1 else k
                rec = recs[fp.rec]
                solid = rec[4][rec[5]['_solidFaces'][0]] if '_solidFaces' in rec[5] else 0
                near_edge = edge_dist(pt, poly) < EDGE
                if near_edge:
                    A['edge'].add(c); A['weld'].add(c); A['weldfar'].add(c)
                if solid >> k & 1:
                    A['weld'].add(c)
                if solid >> far & 1:
                    A['weldfar'].add(c)
        for m in models:
            anchored_cells[m] += len(A[m])
            dist = {a: 0 for a in A[m]}
            q = collections.deque(A[m])
            while q:
                x = q.popleft()
                for n in links.get(x, ()):
                    if n not in dist:
                        dist[n] = dist[x] + 1; q.append(n)
            for members in nets:
                mx = max(dist.get(x, 999) for x in members)
                hist[m][min(mx, 999)] += 1
                if mx > 10:
                    viol[m][os.path.basename(f)[:8]] += 1
    out = {}
    for m in models:
        print(f'{m:8s} anchored cells {anchored_cells[m]:7d}  networks > 10: {sum(viol[m].values()):5d} '
              f'in {len(viol[m]):3d} files   hist 8..12: {[hist[m].get(k, 0) for k in range(8, 13)]}  none: {hist[m].get(999, 0)}')
        out[m] = {'anchored_cells': anchored_cells[m], 'networks_over_10': sum(viol[m].values()),
                  'files_over_10': len(viol[m]), 'networks_by_max_distance': {k: hist[m][k] for k in sorted(hist[m])}}
    json.dump(out, open(os.path.join(HERE, 'power_anchor_stats.json'), 'w'), indent=1)
    return viol, hist


if __name__ == '__main__':
    main()
