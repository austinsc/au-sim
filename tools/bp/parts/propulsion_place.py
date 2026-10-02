"""Placement helpers shared by the propulsion scripts: geometry tables for every part type the
corpus check needs, and world placement at an orientation code (same rule as ../model.py).

Geometry sources, by part hash:
  * propulsion parts: propulsion_geom.geometry() on the prefab and on its " M" twin prefab
  * the 43 logic parts: ../partdb.json (twins: ports reflected along local x, as model.py does)
  * everything else in ../prefab_dump.json or propulsion_prefabs.json: size only (for overlap tests)
"""
import json, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BP = os.path.join(HERE, '..')
sys.path.insert(0, BP)
sys.path.insert(0, HERE)
import hashes
import propulsion_geom as geom

ORI = {int(k): v['rotation'] for k, v in json.load(open(os.path.join(BP, 'orientations.json'))).items()}
OPEN = {0: ((0, 0, 1), (0, 0, -1)), 1: ((0, 1, 0), (0, 0, 1))}      # cable open faces (local), networks.py
CABLES = {0xe60658e2e04f33ce: 'data', 0x743531fcd428bc2c: 'power', 0xe8f9b8dac4e23b9c: 'plasma'}


def rot(m, q):
    return tuple(m[i][0] * q[0] + m[i][1] * q[1] + m[i][2] * q[2] for i in range(3))


def cable_open(k, shape):
    m = ORI[k]
    return {rot(m, o) for o in OPEN.get(shape, ())}


def _mn(size, k):
    m = ORI[k]
    w, h, d = size
    cs = [rot(m, (x, y, z)) for x in (0, w - 1) for y in (0, h - 1) for z in (0, d - 1)]
    return tuple(min(c[a] for c in cs) for a in range(3))


def placer(size, origin, k):
    """local cell -> world cell, for a part whose rotated footprint's min corner is `origin`."""
    m = ORI[k]
    mn = _mn(size, k)
    return lambda q: tuple(origin[a] + rot(m, q)[a] - mn[a] for a in range(3))


def footprint(size, origin, k):
    pl = placer(size, origin, k)
    w, h, d = size
    return {pl((x, y, z)) for x in range(w) for y in range(h) for z in range(d)}


def placed_ports(g, origin, k):
    """[(port index, world port cell, world inward direction, kind, dir)] for geometry g."""
    pl = placer(g['size'], origin, k)
    m = ORI[k]
    out = []
    for i, p in enumerate(g['ports']):
        n = p['normal']
        out.append((i, pl(tuple(p['cell'])), rot(m, (-n[0], -n[1], -n[2])), p['kind'], p['dir']))
    return out


# ---- geometry tables ---------------------------------------------------------------------------

def _size_from_component(hexstr):
    b = bytes.fromhex(hexstr)
    if len(b) < 24:
        return None
    s = struct.unpack_from('<3f', b, 12)
    if all(0.1 <= v <= 10 and abs(v / 0.125 - round(v / 0.125)) < 1e-4 for v in s):
        return tuple(int(round(v / 0.125)) for v in s)
    return None


def generic_sizes():
    """prefab name -> (w, h, d) for every dumped prefab (main component, bytes 12..23)."""
    out = {}
    for f in (os.path.join(BP, 'prefab_dump.json'), os.path.join(HERE, 'propulsion_prefabs.json')):
        for name, nodes in json.load(open(f, encoding='utf-8'))['prefabs'].items():
            for c in nodes[0]['components']:
                s = _size_from_component(c.get('hex', ''))
                if s:
                    out[name.replace(' M', '')] = s
                    break
    return out


def logic_geometry():
    """part hash -> (type_id, geometry) for the partdb logic parts and their twins."""
    db = json.load(open(os.path.join(BP, 'partdb.json'), encoding='utf-8'))
    out = {}
    for t, v in db.items():
        w, h, d = v['size']
        for mirrored, hx in ((False, v['hash']), (True, v.get('mirrored_hash'))):
            if not hx:
                continue
            ports = []
            for name, p in v['ports'].items():
                x, y, z = p['cell']
                if mirrored:
                    x = w - 1 - x
                n = (0, 0, -1) if z < 0 else (0, 0, 1) if z >= d else (-1, 0, 0) if x < 0 else (1, 0, 0)
                ports.append({'name': name, 'cell': [x, y, z], 'normal': list(n), 'kind': 'data', 'dir': p['dir']})
            out[int(hx, 16)] = (t, {'size': [w, h, d], 'ports': ports})
    return out


def propulsion_geometry(prefabs):
    """part hash -> (prefab, mirrored, geometry) for the given prefab names (twins from their own prefab)."""
    out = {}
    have = geom.dump()
    for pf in prefabs:
        for mirrored in (False, True):
            name = pf + ' M' if mirrored else pf
            if name in have:
                out[hashes.part_hash(pf, mirrored)] = (pf, mirrored, geom.geometry(name))
    return out
