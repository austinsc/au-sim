"""Cable support by frames: corpus test of the face list (_solidFaces bit order) and the edge rule.

    python structure_support.py            # prints contact statistics, writes structure_support_stats.json

Anchoring rule (decoded from Burst GarageUpdateCables.UpdateCellsAndPortsJob by the power study, power.md "Q4"):
  a STRAIGHT cable cell probes the 4 sides perpendicular to its axis; when the probe enters a frame, the line from
  the cell centre crosses one of the frame's face polygons (FramePrefabFacesData); the cell is anchored if that face
  is welded (bit i of _solidFaces) or if the crossing point is within 0.08 m of that polygon's edges.
This script supplies the real face polygons (FaceSetupData, structure_prefabs.frame_faces) and tests them:
  * every straight cable cell side-adjacent to a box frame gives a contact (frame, face index, crossing point);
  * contacts are classed 'edge' (within 0.08 m of an edge of the crossed polygon, including the diagonal of the
    split triangular faces) or 'inner', and by whether the face's bit is set ('welded');
  * a wrong face order would put welded bits on faces nobody touches; the right one makes inner contacts sit on
    welded faces far more often than chance.
"""
import collections, json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import structure_corpus as sc  # noqa: E402
import structure_geom as g  # noqa: E402
import structure_occupancy as so  # noqa: E402
import structure_prefabs as sp  # noqa: E402

CELL = 0.125
EDGE = 0.08
OPEN = {0: ((0, 0, 1), (0, 0, -1)), 1: ((0, 1, 0), (0, 0, 1))}
DIRS = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
_FACES = {}


def faces_cells(prefab):
    """Face polygons in canonical continuous cell coordinates (cell i spans [i, i+1)); twins mirrored on x."""
    if prefab not in _FACES:
        size = sp.size_cells(prefab)
        out = []
        for i, f in enumerate(sp.frame_faces(prefab) or []):
            pts = [tuple(v[a] / CELL + size[a] / 2 for a in range(3)) for v in f['verts']]
            out.append((i, f['label'], pts))
        _FACES[prefab] = out
    return _FACES[prefab]


def seg_dist(p, a, b):
    ab = [b[i] - a[i] for i in range(3)]
    ap = [p[i] - a[i] for i in range(3)]
    L = sum(c * c for c in ab)
    t = max(0.0, min(1.0, sum(ab[i] * ap[i] for i in range(3)) / L)) if L else 0.0
    q = [a[i] + t * ab[i] for i in range(3)]
    return math.sqrt(sum((p[i] - q[i]) ** 2 for i in range(3)))


def point_in_poly(p, poly, normal_axis):
    """2D point-in-convex-polygon test after dropping the normal axis (axis-aligned faces only)."""
    ax = [a for a in range(3) if a != normal_axis]
    pts = [(v[ax[0]], v[ax[1]]) for v in poly]
    q = (p[ax[0]], p[ax[1]])
    sign = 0
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        cr = (b[0] - a[0]) * (q[1] - a[1]) - (b[1] - a[1]) * (q[0] - a[0])
        if abs(cr) < 1e-9:
            continue
        s = 1 if cr > 0 else -1
        if sign == 0:
            sign = s
        elif s != sign:
            return False
    return True


def crossing(prefab, mirrored, p_local, d_local):
    """Face crossed by the ray from canonical point p (outside) along canonical direction d (axis-aligned):
    -> (face index, label, min distance to polygon edges in metres) or None."""
    axis = [i for i in range(3) if d_local[i] != 0][0]
    best = None
    for i, label, poly in faces_cells(prefab):
        if mirrored:
            w = sp.size_cells(prefab)[0]
            poly = [(w - v[0], v[1], v[2]) for v in poly]
        if not all(abs(v[axis] - poly[0][axis]) < 1e-6 for v in poly):
            continue                     # only axis-aligned faces can be hit head-on by an axis ray
        t = (poly[0][axis] - p_local[axis]) / d_local[axis]
        if t <= 0:
            continue
        hit = tuple(p_local[a] + t * d_local[a] for a in range(3))
        if not point_in_poly(hit, poly, axis):
            continue
        dist = min(seg_dist(hit, poly[k], poly[(k + 1) % len(poly)]) for k in range(len(poly))) * CELL
        if best is None or t < best[0]:
            best = (t, i, label, dist)
    return None if best is None else best[1:]


def contacts(bps=None, box_only=True):
    """Yield (blueprint name, frame placed dict, face index, face label, edge distance m, welded bit, cable dict)."""
    for bp, placed, occ in so.iter_blueprints(bps):
        for C in placed:
            if C['cat'] != 'cable' or C['rec']['data'][20] != 0:
                continue
            axis_d = g.dir_world(C['rot'], (0, 0, 1))
            c = C['origin']
            for d in DIRS:
                if any(d[i] != 0 and axis_d[i] != 0 for i in range(3)):
                    continue             # only the 4 sides perpendicular to the cable axis
                q = (c[0] + d[0], c[1] + d[1], c[2] + d[2])
                for j in occ.get(q, []):
                    F = placed[j]
                    if F['cat'] != 'frame' or not (F['rec']['fields'] and sc.field(F['rec'], '_solidFaces')):
                        continue
                    faces = faces_cells(F['prefab'])
                    if not faces:
                        continue
                    pl = g.to_local(F['size'], F['origin'], F['rot'], c)
                    p = (pl[0] + 0.5, pl[1] + 0.5, pl[2] + 0.5)
                    dl = g.rot(g.inv(g.ORI[F['rot']]), d)
                    hit = crossing(F['prefab'], F['mirrored'], p, dl)
                    if hit is None:
                        continue
                    fi, label, dist = hit
                    solid = sc.field(F['rec'], '_solidFaces')[0]
                    yield bp['name'], F, fi, label, dist, (solid >> fi) & 1, C


def main():
    stats = collections.defaultdict(collections.Counter)
    alt = collections.defaultdict(collections.Counter)
    # alternative bit orders to compare: JointsArea child order XP, XM, YP, YM, ZP, ZM (box frames only)
    joint_order = ['X+', 'X-', 'Y+', 'Y-', 'Z+', 'Z-']
    diag = collections.Counter()
    for name, F, fi, label, dist, welded, C in contacts():
        key = F['prefab']
        edge = dist <= EDGE + 1e-9
        stats[key][('edge' if edge else 'inner', 'welded' if welded else 'open')] += 1
        solid = sc.field(F['rec'], '_solidFaces')[0]
        if label in joint_order and not edge:
            jb = (solid >> joint_order.index(label)) & 1
            alt[key][('inner', 'welded_by_jointsarea_order' if jb else 'open_by_jointsarea_order')] += 1
        if F['prefab'] == 'SC_FrameA' and not welded:
            diag[('edge' if edge else 'inner', round(dist, 4))] += 1
    out = {}
    for k in sorted(stats):
        s = stats[k]
        out[k] = {f'{a}/{b}': v for (a, b), v in s.items()}
        out[k].update({f'{a}/{b}': v for (a, b), v in alt[k].items()})
        print(k, dict(s), dict(alt[k]))
    print('SC_FrameA unwelded contacts by distance to nearest polygon edge (m):', sorted(diag.items()))
    out['_SC_FrameA_unwelded_by_edge_distance'] = {f'{a} {b}': v for (a, b), v in sorted(diag.items())}
    json.dump(out, open(os.path.join(HERE, 'structure_support_stats.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
