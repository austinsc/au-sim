"""Placement geometry for any prefab (bounding-box footprint) using the same conventions as tools/bp/model.py.

Canonical frame = orientation 16: footprint [0,w) x [0,h) x [0,d). After rotating by orientations.json[k], the
origin stored in the blueprint is the min corner of the rotated footprint.
Sizes come from the prefab dump (root EPC_SC* component, see structure_prefabs.py), so every prefab is covered.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BP = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import structure_prefabs as sp  # noqa: E402

ORI = {int(k): v['rotation'] for k, v in json.load(open(os.path.join(BP, 'orientations.json'))).items()}
SIZE = {n: sp.size_cells(n) for n in sp.DUMP}


def rot(m, q):
    return tuple(sum(m[i][j] * q[j] for j in range(3)) for i in range(3))


def inv(m):
    return [[m[j][i] for j in range(3)] for i in range(3)]


def frame(size, k):
    """-> (rotation matrix, min corner of the rotated footprint)."""
    w, h, d = size
    m = ORI[k]
    corners = [rot(m, (x, y, z)) for x in (0, w - 1) for y in (0, h - 1) for z in (0, d - 1)]
    mn = tuple(min(c[i] for c in corners) for i in range(3))
    return m, mn


def to_world(size, origin, k, q):
    """Canonical cell q (may lie outside the footprint) -> world cell."""
    m, mn = frame(size, k)
    r = rot(m, q)
    return tuple(origin[a] + r[a] - mn[a] for a in range(3))


def to_local(size, origin, k, c):
    """World cell -> canonical cell (inverse of to_world)."""
    m, mn = frame(size, k)
    v = tuple(c[a] - origin[a] + mn[a] for a in range(3))
    return rot(inv(m), v)


def dir_world(k, v):
    return rot(ORI[k], v)


def footprint(size, origin, k):
    w, h, d = size
    return {to_world(size, origin, k, (x, y, z)) for x in range(w) for y in range(h) for z in range(d)}


def bbox_world(size, origin, k):
    """(min corner, max corner inclusive) of the placed footprint."""
    w, h, d = size
    m, mn = frame(size, k)
    ext = [abs(c) for c in rot(m, (w - 1, h - 1, d - 1))]
    hi = [0, 0, 0]
    for a in range(3):
        col = [abs(m[a][j]) for j in range(3)]
        hi[a] = (w - 1) * col[0] + (h - 1) * col[1] + (d - 1) * col[2]
    return tuple(origin), tuple(origin[a] + hi[a] for a in range(3))
