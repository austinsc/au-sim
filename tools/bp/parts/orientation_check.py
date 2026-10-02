"""Which rotation model puts the angled frames' slopes where players put them?

    python orientation_check.py

In real ships an angled piece's slope faces open space (the hull outside, or a room) far more often than it faces
another part. For every angled frame and glass instance in the corpus, this places the piece's convex collider
(structure_meshes.json) under several candidate models and counts how often the cell just beyond a slope face, or
just beyond a full flat face, is occupied by another part. The right model buries the fewest slopes.

Models: R (the orientation table as used by the generator), R transposed (the inverse rotation), and each of those
with the shape mirrored in local x before rotating.
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import corpus  # noqa: E402
import validate_structure as vs  # noqa: E402
import structure_geom as g  # noqa: E402

MESH = json.load(open(os.path.join(HERE, 'structure_meshes.json'), encoding='utf-8'))['parts']
PREFABS = json.load(open(os.path.join(os.path.dirname(HERE), 'prefabs.json'), encoding='utf-8'))
HASH_NAME = {}
for n, v in PREFABS.items():
    HASH_NAME[int(v['hash'], 16)] = n
    if v.get('mirrored_hash'):
        HASH_NAME[int(v['mirrored_hash'], 16)] = n
ANGLED = {n for n, p in MESH.items() if p.get('shape') and p['shape'].get('polygons')}


def sub(a, b): return [a[i] - b[i] for i in range(3)]
def add(a, b): return [a[i] + b[i] for i in range(3)]
def scale(a, s): return [a[i] * s for i in range(3)]
def mat(m, v): return [sum(m[i][j] * v[j] for j in range(3)) for i in range(3)]
def transpose(m): return [[m[j][i] for j in range(3)] for i in range(3)]


def place_poly(name, k, origin, model):
    """World polygons (cells) of the piece's collider under a model."""
    size = MESH[name]['size_cells']
    m = g.ORI[k]
    if model['inverse']:
        m = transpose(m)
    corners = [mat(m, [x, y, z]) for x in (0, size[0]) for y in (0, size[1]) for z in (0, size[2])]
    mn = [min(c[a] for c in corners) for a in range(3)]
    out = []
    for p in MESH[name]['shape']['polygons']:
        vs_ = [list(v) for v in p['verts']]
        nrm = list(p['normal'])
        if model['mirror']:
            vs_ = [[size[0] - v[0], v[1], v[2]] for v in vs_]
            nrm = [-nrm[0], nrm[1], nrm[2]]
        out.append({'slope': p['face'] == 'slope', 'area': p['area'],
                    'verts': [add(sub(mat(m, v), mn), origin) for v in vs_], 'normal': mat(m, nrm)})
    # orient normals outward (away from the centroid)
    allv = [v for q in out for v in q['verts']]
    c = [sum(v[a] for v in allv) / len(allv) for a in range(3)]
    for q in out:
        fc = [sum(v[a] for v in q['verts']) / len(q['verts']) for a in range(3)]
        if sum(q['normal'][a] * (fc[a] - c[a]) for a in range(3)) < 0:
            q['normal'] = scale(q['normal'], -1)
    return out


MODELS = {'R': {'inverse': False, 'mirror': False}, 'R^T': {'inverse': True, 'mirror': False},
          'R, mirrored': {'inverse': False, 'mirror': True}, 'R^T, mirrored': {'inverse': True, 'mirror': True}}


def main():
    bps = corpus.load()
    stats = {m: collections.Counter() for m in MODELS}
    per_type = {m: collections.defaultdict(collections.Counter) for m in MODELS}
    for bp in bps:
        occ = {}
        for i, (h, pos, rot, shape, flags) in enumerate(bp):
            hit = vs.BY_HASH.get(h)
            if hit:
                name, mir = hit
                cells = vs.place(vs.PARTS[name], pos, rot, mir)
            else:
                # any other part: its bounding-box footprint from the prefab size; cables are single cells
                name = HASH_NAME.get(h)
                cells = set(g.footprint(g.SIZE[name], pos, rot)) if name in g.SIZE else {tuple(pos)}
            for c in cells:
                occ[c] = i
        for i, (h, pos, rot, shape, flags) in enumerate(bp):
            hit = vs.BY_HASH.get(h)
            if not hit or hit[0] not in ANGLED or hit[1]:
                continue
            name = hit[0]
            for mname, model in MODELS.items():
                for q in place_poly(name, rot, list(pos), model):
                    vsx = q['verts']
                    fc = [sum(v[a] for v in vsx) / len(vsx) for a in range(3)]
                    pts = [fc] + [add(scale(v, 0.6), scale(fc, 0.4)) for v in vsx]
                    for p in pts:
                        out = add(p, scale(q['normal'], 0.6))
                        cell = tuple(int(x // 1) for x in out)
                        o = occ.get(cell)
                        kind = 'slope' if q['slope'] else 'flat'
                        stats[mname][f'{kind}_n'] += 1
                        per_type[mname][name][f'{kind}_n'] += 1
                        if o is not None and o != i:
                            stats[mname][f'{kind}_buried'] += 1
                            per_type[mname][name][f'{kind}_buried'] += 1
    print('share of samples just beyond a face that land in another part (lower for slopes = better model)')
    for m, s in stats.items():
        print(f'  {m:14s} slopes buried {s["slope_buried"] / max(1, s["slope_n"]):.3f} (n={s["slope_n"]})   '
              f'flat faces touching {s["flat_buried"] / max(1, s["flat_n"]):.3f} (n={s["flat_n"]})')
    print()
    best = min(stats, key=lambda m: stats[m]['slope_buried'] / max(1, stats[m]['slope_n']))
    print('per type, model', best, 'vs R:')
    for name in sorted(per_type['R']):
        a, b = per_type['R'][name], per_type[best][name]
        print(f'  {name:22s} R {a["slope_buried"] / max(1, a["slope_n"]):.2f}  {best} {b["slope_buried"] / max(1, b["slope_n"]):.2f}   n={a["slope_n"]}')


if __name__ == '__main__':
    main()
