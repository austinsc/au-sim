"""Cable networks in the corpus and the part ports they join (rosetta parts only).

Cable cells connect only through open faces (local frame): straight (shape 0) is open at
local ±z, corner (shape 1) at local +y and +z. Two cells connect when each opens toward the
other; a cable joins a part port when the cable in the port cell opens toward the part.
"""
import json, os, sys, collections
sys.path.insert(0, os.path.dirname(__file__))
import corpus

HERE = os.path.dirname(os.path.abspath(__file__))
OPEN = {0: ((0, 0, 1), (0, 0, -1)), 1: ((0, 1, 0), (0, 0, 1))}


def load_model():
    res = json.load(open(os.path.join(HERE, 'parts.json'), encoding='utf-8'))
    ori = {int(k): v for k, v in json.load(open(os.path.join(HERE, 'orientations.json'))).items()}
    return res, ori


def rot(m, q):
    return tuple(sum(m[i][j] * q[j] for j in range(3)) for i in range(3))


def placed_ports(res, ori, t, c, k):
    """[(port_index, world port cell, world direction from the port cell into the part)]."""
    v = res[t]
    m = ori[k]['rotation']
    w, d = v['size_xz']
    rf = [rot(m, (x, 0, z)) for x in range(w) for z in range(d)]
    mn = tuple(min(q[i] for q in rf) for i in range(3))
    out = []
    for i, p in enumerate(v['ports']):
        inward = (0, 0, 1) if p[2] < 0 else (0, 0, -1) if p[2] >= d else (1, 0, 0) if p[0] < 0 else (-1, 0, 0)
        cell = tuple(c[a] + rot(m, p)[a] - mn[a] for a in range(3))
        out.append((i, cell, rot(m, inward)))
    return out


def cable_open(ori, k, shape):
    return {rot(ori[k]['rotation'], o) for o in OPEN.get(shape, ())}


def networks():
    """Yields, per corpus blueprint, a list of networks; each = list of (type_id, port_index)."""
    res, ori = load_model()
    h_to_t = {int(v['hash'], 16): t for t, v in res.items()}
    for bp in corpus.load():
        opens = {c: cable_open(ori, k, sh) for h, c, k, sh, fl in bp if h == corpus.CABLE and k in ori}
        comp = {}; cid = 0
        for c in opens:
            if c in comp: continue
            stack = [c]; comp[c] = cid
            while stack:
                q = stack.pop()
                for d in opens[q]:
                    n = (q[0] + d[0], q[1] + d[1], q[2] + d[2])
                    if n in opens and n not in comp and (-d[0], -d[1], -d[2]) in opens[n]:
                        comp[n] = cid; stack.append(n)
            cid += 1
        nets = collections.defaultdict(list)
        for h, c, k, sh, fl in bp:
            if h in h_to_t and k in ori:
                for i, cell, inward in placed_ports(res, ori, h_to_t[h], c, k):
                    if cell in opens and inward in opens[cell]:
                        nets[comp[cell]].append((h_to_t[h], i))
        yield list(nets.values())
