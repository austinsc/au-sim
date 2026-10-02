"""Prefab-derived geometry for the power / fluid / cable parts (canonical frame = orientation 16).

Sources (all read-only):
  power_prefab_dump.json  (power_prefabs.py) - normal prefabs and their "<name> M" twins
  ../orientations.json     orientation code -> 3x3 rotation on cell indices

Derivation:
  * size: the root EPC component (EPC_SpaceshipComponent base: _mirroredVersion PPtr, then _bounds)
    stores the part's grid size in metres as float3 at byte 12
    (PowerRouter 0.25 x 0.125 x 0.25 -> 2 x 1 x 2 cells). The prefab origin is the footprint centre
    (JointsArea polygons sit exactly on +-size/2).
  * ports (authoritative): the base component's _electricPorts array, in the game's port order
    (Port0, Port1, ... = Localization SC_<X>_PortN rows): u32 count, then per port
    float3 local position (centre of the face cell), i32 face (0 +x, 1 -x, 2 +y, 3 -y, 4 +z, 5 -z),
    i32 SpaceshipPortType (0 DataInput, 1 DataOutput, 2 Power, 3 DataInOut, 4 Plasma, 5 Unset).
    Port cell = face cell + face direction. The array is located by scanning for a count followed by
    records that all sit on the box surface (electric_ports()).
  * cross-check: children "Port ..." carry an EPC_Renderer (floats 0-2 position, 3-5 Unity euler
    angles, mesh id at byte 40: 5663 power, 5855 data input, 6443 data output, 505 plasma,
    704 wireless, 6294 frame port). Every renderer port of the power/fluid parts matches an
    _electricPorts entry; the thrusters' "Port Input Reverse Mode Button" (mesh 5642) is NOT a port.
  * pipes have no electric ports: their pipe ends are the JointsArea polygons that carry a
    non-zero first u32 (the fuel connection index); see fluid_ends().
"""
import json, math, os, struct

HERE = os.path.dirname(os.path.abspath(__file__))
BP = os.path.dirname(HERE)
CELL = 0.125
# all 213 normal prefabs (shared dump, read-only) + this category's twins and extra prefabs
DUMP = dict(json.load(open(os.path.join(BP, 'prefab_dump.json'), encoding='utf-8'))['prefabs'])
DUMP.update(json.load(open(os.path.join(HERE, 'power_prefab_dump.json'), encoding='utf-8'))['prefabs'])
ORI = {int(k): v['rotation'] for k, v in json.load(open(os.path.join(BP, 'orientations.json'))).items()}
MESH_KIND = {5663: ('power', 'both'), 5855: ('data', 'in'), 6443: ('data', 'out'), 505: ('plasma', 'both'),
             704: ('data', 'both'), 6294: ('universal', 'both')}
PORT_TYPE = {0: ('data', 'in'), 1: ('data', 'out'), 2: ('power', 'both'), 3: ('data', 'both'),
             4: ('plasma', 'both'), 5: ('universal', 'both')}
PORT_TYPE_NAME = {0: 'DataInput', 1: 'DataOutput', 2: 'Power', 3: 'DataInOut', 4: 'Plasma', 5: 'Unset'}
FACE_DIR = {0: (1, 0, 0), 1: (-1, 0, 0), 2: (0, 1, 0), 3: (0, -1, 0), 4: (0, 0, 1), 5: (0, 0, -1)}


def euler_matrix(ex, ey, ez):
    """Unity Quaternion.Euler(ex, ey, ez) as a 3x3 matrix (applied Z, then X, then Y)."""
    cx, sx = math.cos(math.radians(ex)), math.sin(math.radians(ex))
    cy, sy = math.cos(math.radians(ey)), math.sin(math.radians(ey))
    cz, sz = math.cos(math.radians(ez)), math.sin(math.radians(ez))
    rx = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    ry = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    rz = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]
    mul = lambda a, b: [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return mul(ry, mul(rx, rz))


def mat_vec(m, v):
    return tuple(sum(m[i][j] * v[j] for j in range(3)) for i in range(3))


def root_component(pf):
    for c in DUMP[pf][0]['components']:
        if c['type'].startswith('EPC_S'):
            return c['type'], bytes.fromhex(c['hex'])
    raise KeyError(pf)


def size_cells(pf):
    _, b = root_component(pf)
    return tuple(int(round(x / CELL)) for x in struct.unpack_from('<3f', b, 12))


def to_cell(pos, size):
    """local position (m, origin = footprint centre) -> cell index (may be outside the footprint)."""
    return tuple(int(math.floor((pos[a] + size[a] * CELL / 2) / CELL)) for a in range(3))


def renderer_ports(pf):
    """[(child name, kind, dir, face cell, port cell, facing)] from the "Port ..." renderers."""
    size = size_cells(pf)
    out = []
    for e in DUMP[pf]:
        name = e['path'].split('/')[-1]
        if not name.startswith('Port'):
            continue
        for c in e['components']:
            if c['type'] != 'EPC_Renderer':
                continue
            b = bytes.fromhex(c['hex'])
            pos = struct.unpack_from('<3f', b, 0)
            eul = struct.unpack_from('<3f', b, 12)
            mesh = struct.unpack_from('<I', b, 40)[0]
            facing = tuple(int(round(x)) for x in mat_vec(euler_matrix(*eul), (0, 0, 1)))
            # renderers sit at the face cell's centre; step a quarter cell inwards in case one
            # sits on the face plane
            inner = tuple(pos[a] - facing[a] * CELL / 4 for a in range(3))
            face = to_cell(inner, size)
            cell = tuple(face[a] + facing[a] for a in range(3))
            kind, d = MESH_KIND.get(mesh, (f'mesh{mesh}', '?'))
            out.append((name, kind, d, face, cell, facing))
    return out


def electric_ports(pf):
    """The root component's _electricPorts array -> (byte offset, [(pos, face code, port type)]) or None."""
    cls, b = root_component(pf)
    if cls == 'EPC_SCCable':
        return None
    size = size_cells(pf)
    half = [s_ * CELL / 2 for s_ in size]
    for o in range(12, len(b) - 4, 4):
        n = struct.unpack_from('<I', b, o)[0]
        if not 1 <= n <= 32 or o + 4 + 20 * n > len(b):
            continue
        recs = []
        for i in range(n):
            x, y, z, face, typ = struct.unpack_from('<3fii', b, o + 4 + 20 * i)
            pos = (x, y, z)
            if any(math.isnan(v) for v in pos) or not (0 <= face <= 5 and 0 <= typ <= 5):
                break
            fa = FACE_DIR[face]
            ax = [abs(c) for c in fa].index(1)
            if abs(pos[ax] * fa[ax] + CELL / 2 - half[ax]) > 1e-4 or any(abs(pos[a]) > half[a] for a in range(3)):
                break
            recs.append((pos, face, typ))
        else:
            return o, recs
    return None


def ports(pf):
    """[(name, kind, dir, face cell, port cell, facing, game index, port type)] in the canonical frame,
    in the game's port order. name = the matching "Port ..." renderer child (or 'Port<i>')."""
    size = size_cells(pf)
    ep = electric_ports(pf)
    if not ep:
        return []
    rend = {(f, fa): n for n, k, d, f, c, fa in renderer_ports(pf)}
    out = []
    for i, (pos, face, typ) in enumerate(ep[1]):
        fa = FACE_DIR[face]
        inner = tuple(pos[a] - fa[a] * CELL / 4 for a in range(3))
        fc = to_cell(inner, size)
        cell = tuple(fc[a] + fa[a] for a in range(3))
        kind, d = PORT_TYPE[typ]
        out.append((rend.get((fc, fa), f'Port{i}'), kind, d, fc, cell, fa, i, PORT_TYPE_NAME[typ]))
    return out


def joint_polys(pf):
    """[(child name, u32 a, u32 b, [vertices])] of SpaceshipComponentAreaPoly components."""
    out = []
    for e in DUMP[pf]:
        for c in e['components']:
            if c['type'] == 'SpaceshipComponentAreaPoly':
                b = bytes.fromhex(c['hex'])
                a, bb, n = struct.unpack_from('<3I', b, 0)
                vs = [struct.unpack_from('<3f', b, 12 + 12 * i) for i in range(n)]
                out.append((e['path'].split('/')[-1], a, bb, vs))
    return out


def fluid_ends(pf):
    """Pipe ends: JointsArea polygons (SpaceshipComponentAreaPoly) whose _type is 1 (pipe end) or 2
    (the decoupling side of SC_PipeDecoupling).

    -> [(child name, connection index, normal, [face cells inside], [cells outside])], canonical frame.
    Each end is a full face rectangle (2 x 2 cells on every pipe)."""
    size = size_cells(pf)
    half = [s * CELL / 2 for s in size]
    out = []
    for name, a, b, vs in joint_polys(pf):
        if a not in (1, 2):          # 1 pipe end, 2 decoupling pipe end (3 = decoupler joint, 0 = plain joint)
            continue
        axis = next(i for i in range(3) if all(abs(v[i] - vs[0][i]) < 1e-4 for v in vs))
        sign = 1 if vs[0][axis] > 0 else -1
        assert abs(abs(vs[0][axis]) - half[axis]) < 1e-4, (pf, name)
        normal = tuple(sign if i == axis else 0 for i in range(3))
        lo = [min(v[i] for v in vs) for i in range(3)]
        hi = [max(v[i] for v in vs) for i in range(3)]
        rng = []
        for i in range(3):
            if i == axis:
                rng.append([size[i] - 1] if sign > 0 else [0])
            else:
                c0 = int(round((lo[i] + half[i]) / CELL)); c1 = int(round((hi[i] + half[i]) / CELL))
                rng.append(list(range(c0, c1)))
        face = [(x, y, z) for x in rng[0] for y in rng[1] for z in rng[2]]
        outside = [tuple(f[i] + normal[i] for i in range(3)) for f in face]
        out.append((name, a, normal, face, outside))
    return out


# ---- placement (same conventions as ../model.py) ---------------------------------------------

def rot(m, q):
    return tuple(sum(m[i][j] * q[j] for j in range(3)) for i in range(3))


_FRAME = {}
_OFFS = {}


def frame(size, k):
    key = (tuple(size), k)
    if key not in _FRAME:
        w, h, d = size
        m = ORI[k]
        corners = [rot(m, (x, y, z)) for x in (0, w - 1) for y in (0, h - 1) for z in (0, d - 1)]
        mn = tuple(min(c[i] for c in corners) for i in range(3))
        _FRAME[key] = (m, mn)
    return _FRAME[key]


def place(size, origin, k, q):
    m, mn = frame(size, k)
    r = rot(m, q)
    return (origin[0] + r[0] - mn[0], origin[1] + r[1] - mn[1], origin[2] + r[2] - mn[2])


def offsets(size, k):
    """Footprint cells relative to the record's cell, for a part of this size at orientation k (cached)."""
    key = (tuple(size), k)
    if key not in _OFFS:
        w, h, d = size
        m, mn = frame(size, k)
        out = []
        for x in range(w):
            for y in range(h):
                for z in range(d):
                    r = rot(m, (x, y, z))
                    out.append((r[0] - mn[0], r[1] - mn[1], r[2] - mn[2]))
        _OFFS[key] = out
    return _OFFS[key]


def footprint(size, origin, k):
    ox, oy, oz = origin
    return {(ox + a, oy + b, oz + c) for a, b, c in offsets(size, k)}


def mirror_x(q, size):
    return (size[0] - 1 - q[0], q[1], q[2])


# ---- every prefab, by part hash ------------------------------------------------------------------

def _hash_table():
    sys_path = BP
    import sys
    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
    import hashes
    prefabs = json.load(open(os.path.join(BP, 'prefabs.json'), encoding='utf-8'))
    names = set(prefabs) | {p for p in DUMP if not p.endswith(' M')}
    out = {}
    for p in names:
        out[hashes.part_hash(p)] = (p, False)
        out[hashes.part_hash(p, True)] = (p, True)
    return out


BY_HASH = _hash_table()
_INFO = {}


def info(prefab, mirrored=False):
    """-> {'size', 'cls', 'ports': [(name, kind, dir, face, cell, facing, index, type)], 'fluid'}.

    A twin uses its own dumped prefab when available, else the normal prefab reflected along x."""
    key = (prefab, mirrored)
    if key in _INFO:
        return _INFO[key]
    src = prefab + ' M' if mirrored and prefab + ' M' in DUMP else prefab
    if src not in DUMP:
        _INFO[key] = None
        return None
    size = size_cells(src)
    ps = ports(src)
    if mirrored and src == prefab:
        ps = [(n, k, d, mirror_x(f, size), mirror_x(c, size), (-fa[0], fa[1], fa[2]), i, t)
              for n, k, d, f, c, fa, i, t in ps]
    fl = fluid_ends(src)
    if mirrored and src == prefab:
        fl = [(n, a, (-nm[0], nm[1], nm[2]), [mirror_x(f, size) for f in fc], [mirror_x(f, size) for f in oc])
              for n, a, nm, fc, oc in fl]
    cls = root_component(src)[0]
    _INFO[key] = {'size': size, 'cls': cls, 'ports': ps, 'fluid': fl, 'src': src}
    return _INFO[key]


def default_color(pf):
    """EPC_SpaceshipComponent._defaultPaintableColor: the int32 just before the _paintableRenderers array
    (count + PPtrs to the "Paintable"... children). 0 on the power parts, 200 on the (non-nano) pipes."""
    pids = {}
    for e in DUMP[pf]:
        for c in e['components']:
            if 'pid' in c:
                pids[c['pid']] = e['path'].split('/')[-1]
    _, b = root_component(pf)
    for o in range(28, len(b) - 16, 4):
        n = struct.unpack_from('<I', b, o)[0]
        if not 1 <= n <= 8:
            continue
        names = []
        for i in range(n):
            fid, pid = struct.unpack_from('<iq', b, o + 4 + 12 * i)
            if fid != 0 or pid not in pids:
                break
            names.append(pids[pid])
        else:
            if any('Paint' in x for x in names):
                return struct.unpack_from('<i', b, o - 4)[0]
    return None


def twin_check(prefab):
    """True if the dumped twin prefab's ports / pipe ends equal the x-reflection of the normal prefab's,
    None if there is no twin prefab."""
    if prefab + ' M' not in DUMP:
        return None
    size = size_cells(prefab)
    refl = sorted((mirror_x(f, size), mirror_x(c, size), (-fa[0], fa[1], fa[2]), k, d, i)
                  for n, k, d, f, c, fa, i, t in ports(prefab))
    twin = sorted((f, c, fa, k, d, i) for n, k, d, f, c, fa, i, t in ports(prefab + ' M'))
    rf = sorted((tuple(sorted(mirror_x(q, size) for q in fc)), (-nm[0], nm[1], nm[2]))
                for n, a, nm, fc, oc in fluid_ends(prefab))
    tf = sorted((tuple(sorted(fc)), nm) for n, a, nm, fc, oc in fluid_ends(prefab + ' M'))
    return refl == twin and rf == tf and size_cells(prefab + ' M') == size
