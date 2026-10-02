"""Cable cells around placed parts, in the part's canonical (orientation-16) frame.

For every instance of the requested prefabs, every cable cell (data/power/plasma) adjacent to the footprint that
OPENS toward it (open-face rule of tools/bp/networks.py) is reported as (canonical port cell, canonical face cell,
cable kind). Mirrored twins are reported in the twin's own canonical frame (no reflection applied), so a twin's
statistics can be compared with the normal part reflected along x (dx -> w-1-dx).

    python structure_cables.py SC_FrameQuarterPorts SC_FrameQuarterPortsCorner
"""
import collections, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import structure_occupancy as so  # noqa: E402
import structure_geom as g  # noqa: E402

OPEN = {0: ((0, 0, 1), (0, 0, -1)), 1: ((0, 1, 0), (0, 0, 1))}
DIRS = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
KIND = {'SC_DataCable': 'data', 'SC_PowerCable': 'power', 'SC_PlasmaCable': 'plasma'}


def cable_opens(P):
    sh = P['rec']['data'][20]
    return {g.dir_world(P['rot'], o) for o in OPEN.get(sh, ())}


def touching_cables(targets, bps=None):
    """-> {(prefab, mirrored): Counter{(port_cell, face_cell, kind): n}}, instance counts, per-instance hit lists."""
    stats = collections.defaultdict(collections.Counter)
    n_inst = collections.Counter()
    per_instance = []
    for bp, placed, occ in so.iter_blueprints(bps):
        cables = {}
        for P in placed:
            if P['cat'] == 'cable':
                cables[P['origin']] = P
        for P in placed:
            if P['prefab'] not in targets:
                continue
            key = (P['prefab'], P['mirrored'])
            n_inst[key] += 1
            hits = []
            for c in P['cells']:
                for d in DIRS:
                    q = (c[0] + d[0], c[1] + d[1], c[2] + d[2])
                    if q in P['cells'] or q not in cables:
                        continue
                    C = cables[q]
                    back = (-d[0], -d[1], -d[2])
                    if back not in cable_opens(C):
                        continue
                    pc = g.to_local(P['size'], P['origin'], P['rot'], q)
                    fc = g.to_local(P['size'], P['origin'], P['rot'], c)
                    hits.append((pc, fc, KIND[C['prefab']]))
            for h in hits:
                stats[key][h] += 1
            per_instance.append((bp['name'], key, P, hits))
    return stats, n_inst, per_instance


if __name__ == '__main__':
    targets = set(sys.argv[1:])
    stats, n_inst, _ = touching_cables(targets)
    for key in sorted(stats, key=str):
        print(key, 'instances', n_inst[key])
        for (pc, fc, kind), n in sorted(stats[key].items(), key=lambda kv: -kv[1]):
            print(f'    port cell {pc} face {fc} {kind:6s} {n}')
