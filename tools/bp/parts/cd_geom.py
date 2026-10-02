"""Prefab-derived geometry for any SC_* part (used for controls_displays.json).

Rules (all checked against the 43 logic parts of partdb.json: 43/43 identical, see validate_controls_displays.py):
  * size: the root EPC_SC* component (EPC_SpaceshipComponent base) stores the bounding size in metres as
    float3 at byte 12. Footprint = that box centred on the prefab origin; 1 cell = 0.125 m.
  * ports: child nodes named "Port ..."; their EPC_Renderer position (bytes 0-11) is the centre of the face
    cell inside the part, the euler rotation (bytes 12-23, Unity ZXY order, R = Ry*Rx*Rz) turns the port
    mesh's +z into the port's outward facing. Port cell (outside) = face cell + facing.
  * canonical frame = orientation 16, origin = min corner of the footprint.
  * a mirrored twin is its own prefab "<name> M" (exists in the game assets for most parts); its port nodes
    sit at x-reflected positions with x-reflected facing, i.e. dx -> w-1-dx.
Placement in a blueprint: rotate with orientations.json, re-anchor at the rotated footprint's min corner
(same as tools/bp/model.py).
"""
import json, math, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BP = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import cd_prefab as P  # noqa: E402

ORI = {int(k): v['rotation'] for k, v in json.load(open(os.path.join(BP, 'orientations.json'))).items()}
CELL = 0.125


def _rx(a):
    c, s = math.cos(a), math.sin(a); return [[1, 0, 0], [0, c, -s], [0, s, c]]


def _ry(a):
    c, s = math.cos(a), math.sin(a); return [[c, 0, s], [0, 1, 0], [-s, 0, c]]


def _rz(a):
    c, s = math.cos(a), math.sin(a); return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def _mm(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def facing(euler):
    """Unity euler (deg) -> outward unit axis of a port mesh (its local +z)."""
    ex, ey, ez = (math.radians(v) for v in euler)
    r = _mm(_ry(ey), _mm(_rx(ex), _rz(ez)))
    v = tuple(int(round(r[i][2])) for i in range(3))
    assert sum(abs(c) for c in v) == 1, (euler, v)
    return v


def root_size(prefab):
    root = P.nodes(prefab)[0]
    comp = next(c for c in root['components'] if c['type'].startswith('EPC_'))
    sx, sy, sz = struct.unpack_from('<3f', bytes.fromhex(comp['hex']), 12)
    size = [sx / CELL, sy / CELL, sz / CELL]
    assert all(abs(v - round(v)) < 1e-3 for v in size), (prefab, size)
    return [int(round(v)) for v in size], comp['type']


def geometry(prefab):
    """-> {'size': [w,h,d], 'root': class, 'ports': {node: {'face': (x,y,z), 'facing': (dx,dy,dz), 'cell': (x,y,z),
    'pos': [...], 'offcentre': bool}}} in the canonical frame (origin = footprint min corner)."""
    (w, h, d), cls = root_size(prefab)
    mn = (-w * CELL / 2, -h * CELL / 2, -d * CELL / 2)
    ports = {}
    for path, r in P.port_nodes(prefab):
        if r is None:
            continue
        f = facing(r['rot'])
        u = [(r['pos'][i] - mn[i]) / CELL for i in range(3)]
        face = tuple(int(math.floor(u[i] - 0.01 * f[i])) for i in range(3))
        off = any(abs((u[i] % 1) - 0.5) > 0.02 for i in range(3))
        inside = all(0 <= face[i] < (w, h, d)[i] for i in range(3))
        cell = tuple(face[i] + f[i] for i in range(3))
        ports[path.split('/', 1)[1]] = {'face': face, 'facing': f, 'cell': cell, 'pos': r['pos'],
                                        'offcentre': off, 'inside': inside}
    return {'size': [w, h, d], 'root': cls, 'ports': ports}


def rot(m, q):
    return tuple(sum(m[i][j] * q[j] for j in range(3)) for i in range(3))


def placer(size, k):
    """-> function canonical cell -> world offset from the placed origin (min-corner anchoring)."""
    w, h, d = size
    m = ORI[k]
    corners = [rot(m, (x, y, z)) for x in (0, w - 1) for y in (0, h - 1) for z in (0, d - 1)]
    mn = tuple(min(c[i] for c in corners) for i in range(3))
    return lambda q: tuple(rot(m, q)[i] - mn[i] for i in range(3)), m


def place(geom, origin, k):
    """World footprint (set of cells) and ports {node: (port cell, face cell, inward dir)}."""
    w, h, d = geom['size']
    f, m = placer(geom['size'], k)
    wc = lambda q: tuple(origin[i] + f(q)[i] for i in range(3))
    foot = {wc((x, y, z)) for x in range(w) for y in range(h) for z in range(d)}
    ports = {}
    for n, p in geom['ports'].items():
        pc, fc = wc(p['cell']), wc(p['face'])
        ports[n] = (pc, fc, tuple(fc[i] - pc[i] for i in range(3)))
    return foot, ports


def reflect(geom):
    """The mirrored twin by rule: x -> w-1-x for face/port cells, facing x negated."""
    w = geom['size'][0]
    out = {'size': list(geom['size']), 'root': geom['root'], 'ports': {}}
    for n, p in geom['ports'].items():
        fx = p['face']; f = p['facing']
        face = (w - 1 - fx[0], fx[1], fx[2]); fac = (-f[0], f[1], f[2])
        out['ports'][n] = dict(p, face=face, facing=fac, cell=tuple(face[i] + fac[i] for i in range(3)))
    return out
