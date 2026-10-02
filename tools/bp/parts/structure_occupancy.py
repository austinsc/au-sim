"""Per-blueprint occupancy maps for the structure study.

    import structure_occupancy as so
    for bp, placed, occ in so.iter_blueprints():
        placed: list of dicts {i, prefab, mirrored, origin, rot, size, cells (set), rec}
        occ:    {world cell: [index into placed, ...]}
"""
import collections, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import structure_corpus as sc  # noqa: E402
import structure_geom as g  # noqa: E402

CABLE_NAMES = ('SC_DataCable', 'SC_PowerCable', 'SC_PlasmaCable')


def category(p):
    if p in CABLE_NAMES:
        return 'cable'
    if re.match(r'SC_(Frame|Window|Decoupler|Nanoframe)', p):
        return 'frame'
    if re.match(r'SC_Glass', p):
        return 'glass'
    if re.match(r'SC_Label', p):
        return 'label'
    return 'other'


def place(bp):
    placed = []
    occ = collections.defaultdict(list)
    for r in bp['parts']:
        n = sc.NAME.get(r['part'])
        if not n or r['rot'] not in g.ORI:
            continue
        p, m = n
        size = g.SIZE[p]
        origin = (r['x'], r['y'], r['z'])
        cells = g.footprint(size, origin, r['rot'])
        idx = len(placed)
        placed.append({'i': idx, 'prefab': p, 'mirrored': m, 'origin': origin, 'rot': r['rot'], 'size': size,
                       'cells': cells, 'rec': r, 'cat': category(p)})
        for c in cells:
            occ[c].append(idx)
    return placed, occ


def iter_blueprints(bps=None):
    for bp in (bps if bps is not None else sc.load()):
        placed, occ = place(bp)
        yield bp, placed, occ
