"""Corpus analysis engine for controls_displays (geometry from cd_geom, records from cd_corpus).

Per blueprint: cable cells with their open faces (data, power, plasma), every part with a known prefab
geometry (root-size box, min-corner anchored; ports from the "Port ..." nodes; twins from their own
prefab when dumped, else by reflection), an AABB bucket index for overlap/contact queries, and lazy
cable-network walks (same-kind cables joined through mutually open faces) from a given port.
"""
import collections, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BP = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, BP)
import cd_geom as G, cd_prefab as P, cd_corpus as C, cd_geom_ports as GP, hashes  # noqa: E402

OPEN = {0: ((0, 0, 1), (0, 0, -1)), 1: ((0, 1, 0), (0, 0, 1))}
PREFABS = json.load(open(os.path.join(BP, 'prefabs.json'), encoding='utf-8'))
DIRS = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
BUCKET = 8


def _types(pf):
    try:
        return {n: t for n, f, t in GP.port_table(pf)[1]}
    except Exception:
        return {}


def _bbox_geometry(pf):
    """Fallback for prefabs whose root carries no size (glass): the JointsArea polygons' box, if centred."""
    bb = P.poly_bbox(pf)
    if not bb:
        return None
    lo, hi = bb
    if any(abs(lo[a] + hi[a]) > 1e-4 or hi[a] <= 0 for a in range(3)):
        return None
    size = [int(round(2 * hi[a] / G.CELL)) for a in range(3)]
    return {'size': size, 'root': 'poly-bbox', 'ports': {}, 'aabb_only': True}


def all_geometries():
    """part hash -> (prefab, mirrored, geometry or None, {node: game port type})."""
    out = {}
    names = set(PREFABS) | {k for k in P.dump() if not k.endswith(' M')}
    for pf in names:
        try:
            g = G.geometry(pf)
            if min(g['size']) <= 0:
                g = None
        except Exception:
            g = None
        if g is None:
            g = _bbox_geometry(pf)
            if g is not None:
                out[hashes.part_hash(pf)] = (pf, False, g, {})
                out[hashes.part_hash(pf, True)] = (pf, True, g, {})
                continue
        ty = _types(pf) if g else {}
        out[hashes.part_hash(pf)] = (pf, False, g, ty)
        gt = None
        if g is not None:
            tw = pf + ' M'
            try:
                gt = G.geometry(tw) if tw in P.dump() else G.reflect(g)
            except Exception:
                gt = G.reflect(g)
        out[hashes.part_hash(pf, True)] = (pf, True, gt, ty)
    return out


GEOM = all_geometries()


def extent(size, k):
    """World extent (dx, dy, dz) of a w x h x d part at orientation k."""
    m = G.ORI[k]
    return tuple(sum(abs(m[i][j]) * size[j] for j in range(3)) for i in range(3))


class Blueprint:
    def __init__(self, bp):
        self.bp = bp
        self.cables = {}
        for i, r in enumerate(bp):
            cs = C.cable_shape(r)
            if cs:
                kind, shape = cs
                m = G.ORI[r.rot]
                self.cables[r.cell] = (kind, frozenset(G.rot(m, o) for o in OPEN.get(shape, ())))
        self.parts = {}                              # record index -> dict
        self.buckets = collections.defaultdict(list)
        self.port_at = collections.defaultdict(list)  # port cell -> [(rec idx, node, face cell, inward)]
        for i, r in enumerate(bp):
            if r.part in C.CABLES:
                continue
            info = GEOM.get(r.part)
            if not info or info[2] is None:
                continue
            pf, mir, g, ty = info
            ext = extent(g['size'], r.rot)
            lo = r.cell
            hi = tuple(lo[a] + ext[a] - 1 for a in range(3))
            f, _ = G.placer(g['size'], r.rot)
            ports = {}
            for n, p in g['ports'].items():
                pc = tuple(lo[a] + f(p['cell'])[a] for a in range(3))
                fc = tuple(lo[a] + f(p['face'])[a] for a in range(3))
                ports[n] = (pc, fc, tuple(fc[a] - pc[a] for a in range(3)))
                self.port_at[pc].append((i, n, fc, ports[n][2]))
            self.parts[i] = {'prefab': pf, 'mirrored': mir, 'geom': g, 'types': ty, 'lo': lo, 'hi': hi,
                             'ports': ports, 'place': f}
            for bx in range(lo[0] // BUCKET, hi[0] // BUCKET + 1):
                for by in range(lo[1] // BUCKET, hi[1] // BUCKET + 1):
                    for bz in range(lo[2] // BUCKET, hi[2] // BUCKET + 1):
                        self.buckets[(bx, by, bz)].append(i)

    def parts_at(self, c, exclude=None):
        out = []
        for i in self.buckets.get((c[0] // BUCKET, c[1] // BUCKET, c[2] // BUCKET), ()):
            if i == exclude:
                continue
            p = self.parts[i]
            if all(p['lo'][a] <= c[a] <= p['hi'][a] for a in range(3)):
                out.append(i)
        return out

    def overlapping(self, i):
        p = self.parts[i]
        lo, hi = p['lo'], p['hi']
        seen = set()
        for bx in range(lo[0] // BUCKET, hi[0] // BUCKET + 1):
            for by in range(lo[1] // BUCKET, hi[1] // BUCKET + 1):
                for bz in range(lo[2] // BUCKET, hi[2] // BUCKET + 1):
                    for j in self.buckets.get((bx, by, bz), ()):
                        if j == i or j in seen:
                            continue
                        q = self.parts[j]
                        if all(q['lo'][a] <= hi[a] and lo[a] <= q['hi'][a] for a in range(3)):
                            seen.add(j)
        return seen

    def footprint(self, i):
        p = self.parts[i]
        lo, hi = p['lo'], p['hi']
        return [(x, y, z) for x in range(lo[0], hi[0] + 1) for y in range(lo[1], hi[1] + 1)
                for z in range(lo[2], hi[2] + 1)]

    def network(self, start):
        """Cable cells reachable from cable cell `start` (same kind, mutually open faces)."""
        kind = self.cables[start][0]
        seen = {start}
        st = [start]
        while st:
            q = st.pop()
            for d in self.cables[q][1]:
                n = (q[0] + d[0], q[1] + d[1], q[2] + d[2])
                if n in seen or n not in self.cables:
                    continue
                kn, on = self.cables[n]
                if kn == kind and (-d[0], -d[1], -d[2]) in on:
                    seen.add(n)
                    st.append(n)
        return seen

    def endpoints(self, cells):
        """Ports joined by a network: [(rec idx, node, kind)] where the cable in the port cell opens toward the part."""
        out = []
        for c in cells:
            kind, opens = self.cables[c]
            for (i, n, fc, inward) in self.port_at.get(c, ()):
                if inward in opens:
                    out.append((i, n, kind))
        return out
