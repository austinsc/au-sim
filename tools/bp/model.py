"""Placement geometry for logic parts (normal or mirrored twin) at any orientation code.

Canonical frame = orientation 16: footprint [0,w) x [0,h) x [0,d); inputs/outputs sit in the
cell just outside the back (z = -1) or front (z = d) face. A mirrored twin has the same ports
reflected along local x (dx -> w-1-dx). After rotating, the origin is the footprint's min corner.
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
DB = json.load(open(os.path.join(HERE, 'partdb.json'), encoding='utf-8'))
ORI = {int(k): v for k, v in json.load(open(os.path.join(HERE, 'orientations.json'))).items()}

# part hash -> (type_id, mirrored?)
BY_HASH = {}
for _t, _v in DB.items():
    BY_HASH[int(_v['hash'], 16)] = (_t, False)
    if _v.get('mirrored_hash'):
        BY_HASH[int(_v['mirrored_hash'], 16)] = (_t, True)


def rot(m, q):
    return tuple(sum(m[i][j] * q[j] for j in range(3)) for i in range(3))


def _frame(t, k):
    w, h, d = DB[t]['size']
    m = ORI[k]['rotation']
    cells = [rot(m, (x, y, z)) for x in range(w) for y in range(h) for z in range(d)]
    mn = tuple(min(c[i] for c in cells) for i in range(3))
    return m, mn, (w, h, d)


def footprint(t, origin, k):
    m, mn, (w, h, d) = _frame(t, k)
    return {tuple(origin[a] + rot(m, (x, y, z))[a] - mn[a] for a in range(3))
            for x in range(w) for y in range(h) for z in range(d)}


def ports(t, origin, k, mirrored=False):
    """{name: {'cell': port cell (outside), 'face': footprint cell it touches, 'inward': dir, 'dir': in/out/both}}"""
    m, mn, (w, h, d) = _frame(t, k)
    place = lambda q: tuple(origin[a] + rot(m, q)[a] - mn[a] for a in range(3))
    out = {}
    for name, p in DB[t]['ports'].items():
        x, y, z = p['cell']
        if mirrored:
            x = w - 1 - x
        face = (x, y, 0 if z < 0 else d - 1) if z < 0 or z >= d else (0 if x < 0 else w - 1, y, z)
        pc, fc = place((x, y, z)), place(face)
        out[name] = {'cell': pc, 'face': fc, 'inward': tuple(fc[a] - pc[a] for a in range(3)), 'dir': p['dir']}
    return out
