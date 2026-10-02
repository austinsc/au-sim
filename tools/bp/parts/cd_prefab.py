"""Prefab geometry helpers for the controls/displays/cameras/monitors parts (controls_displays.json).

Reads tools/bp/prefab_dump.json (read-only) and decodes the components that carry geometry:
  EPC_Renderer      f32 pos(3) @0, euler deg(3) @12, scale(3) @24  -- the reliable local transform
  DOTSColliderBox   u32 0, then 9 f32 (see collider_box) -- size/0.125 ~ footprint
Port children are named "Port ..." ("Port Power" = power port).

    python cd_prefab.py SC_Button [SC_Switch ...]     -> prints a readable hierarchy
"""
import json, os, struct, sys, math

HERE = os.path.dirname(os.path.abspath(__file__))
BP = os.path.dirname(HERE)
_DUMP = None


def dump():
    """prefab name -> node list; tools/bp/prefab_dump.json plus cd_prefab_extra.json (twins, unseen prefabs)."""
    global _DUMP
    if _DUMP is None:
        _DUMP = dict(json.load(open(os.path.join(BP, 'prefab_dump.json'), encoding='utf-8'))['prefabs'])
        extra = os.path.join(HERE, 'cd_prefab_extra.json')
        if os.path.exists(extra):
            for k, v in json.load(open(extra, encoding='utf-8'))['prefabs'].items():
                _DUMP.setdefault(k, v)
    return _DUMP


def all_sc_gameobjects():
    extra = os.path.join(HERE, 'cd_prefab_extra.json')
    return set(json.load(open(extra, encoding='utf-8'))['all_sc_gameobjects'])


def floats(hexstr, n=None, off=0):
    b = bytes.fromhex(hexstr)
    k = (len(b) - off) // 4 if n is None else n
    return list(struct.unpack_from('<%df' % k, b, off))


def renderer(hexstr):
    f = floats(hexstr, 9)
    b = bytes.fromhex(hexstr)
    mesh = struct.unpack_from('<i', b, 40)[0] if len(b) >= 44 else None
    return {'pos': [round(v, 5) for v in f[0:3]], 'rot': [round(v, 3) for v in f[3:6]],
            'scale': [round(v, 5) for v in f[6:9]], 'mesh': mesh}


def collider_box(hexstr):
    """DOTSColliderBox / Sphere / Capsule: f32 list. Box = centre(3), euler deg(3), size(3, metres), bevel."""
    b = bytes.fromhex(hexstr)
    f = list(struct.unpack_from('<%df' % (len(b) // 4), b, 0))
    return [round(v, 5) for v in f]


def area_poly(hexstr):
    """SpaceshipComponentAreaPoly: u32 flags0, u32 flags1, u32 n, n x float3 (root-local metres)."""
    b = bytes.fromhex(hexstr)
    a0, a1, n = struct.unpack_from('<III', b, 0)
    pts = [tuple(round(v, 5) for v in struct.unpack_from('<3f', b, 12 + 12 * i)) for i in range(n)]
    return a0, a1, pts


def polys(prefab):
    out = []
    for e in nodes(prefab):
        for c in e['components']:
            if c['type'] == 'SpaceshipComponentAreaPoly':
                a0, a1, pts = area_poly(c['hex'])
                out.append((e['path'].split('/')[-1], a0, a1, pts))
    return out


def poly_bbox(prefab):
    pts = [p for _, _, _, ps in polys(prefab) for p in ps]
    if not pts:
        return None
    return [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]


def port_nodes(prefab):
    """[(name, renderer dict)] for children named 'Port ...' (first EPC_Renderer on that node)."""
    out = []
    for e in nodes(prefab):
        nm = e['path'].split('/')[-1]
        if nm.startswith('Port'):
            r = next((renderer(c['hex']) for c in e['components'] if c['type'] == 'EPC_Renderer'), None)
            out.append((e['path'], r))
    return out


def nodes(prefab):
    return dump()[prefab]


def show(prefab, full_hex=False):
    print('=' * 10, prefab, 'poly bbox', poly_bbox(prefab))
    for e in nodes(prefab):
        print(e['path'], '' if e.get('active', True) else '(inactive)')
        for c in e['components']:
            t = c['type']
            h = c.get('hex', '')
            if t == 'EPC_Renderer':
                r = renderer(h)
                print('    EPC_Renderer pos', r['pos'], 'rot', r['rot'], 'scale', r['scale'], 'mesh', r['mesh'])
            elif t == 'DOTSColliderBox':
                print('    DOTSColliderBox', collider_box(h))
            elif t in ('DOTSColliderSphere', 'DOTSColliderCapsule'):
                print('   ', t, collider_box(h))
            elif t == 'SpaceshipComponentAreaPoly':
                a0, a1, pts = area_poly(h)
                print('    AreaPoly', a0, a1, pts)
            else:
                print('   ', t, h if full_hex else h[:160])


if __name__ == '__main__':
    for p in sys.argv[1:]:
        show(p, full_hex='--hex' in sys.argv)
