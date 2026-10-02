"""Helpers for deriving and validating the sensor parts (tools/bp/parts/sensors.json; driver: validate_sensors.py).

Three jobs:
  1. read a part prefab (tools/bp/prefab_dump.json, plus tools/bp/parts/sensors_prefabs.json for the mirrored twins
     and the prefabs the shared dump lacks) and derive its grid geometry, ports and settings struct;
  2. place a part (normal or mirrored twin) at any orientation code, like tools/bp/model.py does for logic parts;
  3. load the blueprint corpus with per-record GUIDs, struct hashes, settings bytes and cable shapes for all three
     cable types (data, power, plasma), and check placed parts against it.

Rules used (each one checked, see sensors.md):
  * Footprint = the size field of the part's main EPC_SC<Class> component (body bytes 12..23, metres), centred on
    the prefab origin. Holds for all 43 logic parts in partdb.json and for the corpus sensors (incl. the tanks).
  * Frames: the prefab frame is Unity's (x right, y up, z forward; Euler order Z, X, Y). The canonical grid frame
    (orientation 16) has the same axes with the origin at the footprint's min corner: a prefab point p lies in cell
    floor((p - lo) / 0.125), lo = -size / 2. No axis flip (all 43 logic parts + 5 twins land on partdb's cells).
  * Ports: the main component bakes a port list (game port order; see baked_ports). The "Port ..." children carry
    an EPC_Renderer at the face-cell centre whose local +z (rotated by its Euler angles) points out of the part, and
    whose mesh id gives the kind: 0x192b data output, 0x16df data input, 0x161f power, 0x01f9 plasma,
    0x02c0 wireless (both). The two sources agree on every dumped part. Port cell = face cell + facing.
  * Twins ("<prefab> M") are the normal ports reflected along local x (dx -> w-1-dx), facing x negated.
  * Settings struct = the nearest class in the IL2CPP inheritance chain that declares a nested Blueprint type
    (196 of 196 corpus-backed prefabs agree; blueprint_struct).
"""
import glob, json, math, os, pickle, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BP = os.path.dirname(HERE)
sys.path.insert(0, BP)
import bpformat, hashes  # noqa: E402  (shared, read-only)

CELL = 0.125
ORI = {int(k): v['rotation'] for k, v in json.load(open(os.path.join(BP, 'orientations.json'))).items()}
MESH_KIND = {0x192b: ('data', 'out'), 0x16df: ('data', 'in'), 0x161f: ('power', 'in'),
             0x01f9: ('plasma', 'both'), 0x02c0: ('data', 'both')}
CABLES = {hashes.part_hash('SC_DataCable'): 'data', hashes.part_hash('SC_PowerCable'): 'power',
          hashes.part_hash('SC_PlasmaCable'): 'plasma'}
OPEN = {0: ((0, 0, 1), (0, 0, -1)), 1: ((0, 1, 0), (0, 0, 1))}   # cable shape -> open faces (local)


# ---------------------------------------------------------------- prefabs

def load_prefabs():
    """{prefab name: [node, ...]} from the shared dump plus this category's own dump (twins, extra prefabs)."""
    out = dict(json.load(open(os.path.join(BP, 'prefab_dump.json'), encoding='utf-8'))['prefabs'])
    own = os.path.join(HERE, 'sensors_prefabs.json')
    if os.path.exists(own):
        out.update(json.load(open(own, encoding='utf-8'))['prefabs'])
    return out


def euler_forward(ex, ey, ez):
    """Unity Quaternion.Euler(ex, ey, ez) * Vector3.forward (rotation order Z, X, Y), rounded to a grid axis."""
    rx, ry = math.radians(ex), math.radians(ey)
    # Rz leaves forward unchanged; Rx(ex)·(0,0,1) = (0, -sin ex, cos ex); then Ry(ey)
    v = (0.0, -math.sin(rx), math.cos(rx))
    v = (v[0] * math.cos(ry) + v[2] * math.sin(ry), v[1], -v[0] * math.sin(ry) + v[2] * math.cos(ry))
    r = tuple(int(round(c)) for c in v)
    assert sum(abs(c) for c in r) == 1, (ex, ey, ez, v)
    return r


def parse_prefab(nodes):
    """-> dict(cls, size_m, joints [(polygon pts)], colliders [(path, centre, size)], ports [...])"""
    root = nodes[0]
    cls, size_m, body = None, None, None
    for c in root['components']:
        if c.get('hex') is not None and c['type'].startswith('EPC_SC'):
            body = bytes.fromhex(c['hex'])
            cls, size_m = c['type'], struct.unpack_from('<3f', body, 12)
            break
    joints, colliders, ports = [], [], []
    for e in nodes[1:]:
        name = e['path'].split('/')[-1]
        sub = e['path'].split('/', 1)[-1]
        for c in e['components']:
            h = c.get('hex')
            if h is None:
                continue
            b = bytes.fromhex(h)
            if c['type'] == 'SpaceshipComponentAreaPoly':
                n = struct.unpack_from('<I', b, 8)[0]
                joints.append((sub, [struct.unpack_from('<3f', b, 12 + 12 * i) for i in range(n)]))
            elif c['type'] == 'DOTSColliderBox':
                f = struct.unpack_from('<9f', b, 4)
                colliders.append((sub, f[0:3], f[6:9]))
            elif c['type'] == 'EPC_Renderer' and name.startswith('Port'):
                f = struct.unpack_from('<9f', b, 0)
                mesh = struct.unpack_from('<I', b, 40)[0]
                kind, d = MESH_KIND.get(mesh, ('?', '?'))
                ports.append({'node': name, 'pos': f[0:3], 'euler': f[3:6], 'mesh': mesh, 'kind': kind, 'dir': d,
                              'facing': euler_forward(*f[3:6]), 'active': e.get('active', True)})
    return {'cls': cls, 'size_m': size_m, 'joints': joints, 'colliders': colliders, 'ports': ports, 'body': body}


FACING = {0: (1, 0, 0), 1: (-1, 0, 0), 2: (0, 1, 0), 3: (0, -1, 0), 4: (0, 0, 1), 5: (0, 0, -1)}
PORT_TYPE = {0: ('data', 'in'), 1: ('data', 'out'), 2: ('power', 'in')}


def baked_ports(body, renderer_ports=()):
    """The port list baked into the part's main component (EPC_SC<Class> body), in the game's port order
    (= Localization SC_<Key>_Port0..N, = the simulator's port order):
        u32 count, count x { f32 pos[3] (prefab metres, face-cell centre); i32 facing (0..5 = +x,-x,+y,-y,+z,-z);
                             i32 type (0 data input, 1 data output, 2 power) }
    Its offset depends on the class (136 on most sensors, 160 on the Condition), so it is searched for: the first
    offset whose entries all decode sanely and, when port renderers exist, sit exactly on their positions.
    -> [(pos, facing code, type)] or None"""
    want = {tuple(round(c, 4) for c in p['pos']) for p in renderer_ports}
    if not want:
        return []          # no port children: no ports (a blind search only finds look-alike data)
    for o in range(0, len(body) - 4, 4):
        n = struct.unpack_from('<I', body, o)[0]
        if not 0 < n <= 16 or o + 4 + 20 * n > len(body):
            continue
        ents = []
        for i in range(n):
            q = o + 4 + 20 * i
            pos = struct.unpack_from('<3f', body, q)
            code, typ = struct.unpack_from('<2i', body, q + 12)
            if code not in FACING or not 0 <= typ <= 3 or any(abs(c) > 8 or abs(c * 16 - round(c * 16)) > 1e-4
                                                              for c in pos):
                break
            ents.append((pos, code, typ))
        else:
            if {tuple(round(c, 4) for c in e[0]) for e in ents} == want:
                return ents
    return None


def joints_bbox(joints):
    pts = [p for _, poly in joints for p in poly]
    if not pts:
        return None
    return tuple(min(p[i] for p in pts) for i in range(3)), tuple(max(p[i] for p in pts) for i in range(3))


def cells_of(lo_m, size_cells, p):
    """Prefab point (metres) -> canonical cell, for a box whose min corner is lo_m."""
    return tuple(int(math.floor((p[i] - lo_m[i]) / CELL + 1e-6)) for i in range(3))


def derive_geometry(pf, lo_m=None, size=None):
    """Grid geometry from a parsed prefab. Default box: the size field, centred on the prefab origin.
    -> {'size': [w,h,d], 'lo_m': ..., 'ports': [{node, cell, face, kind, dir, facing}]}"""
    if size is None:
        size = [int(round(s / CELL)) for s in pf['size_m']]
    if lo_m is None:
        lo_m = tuple(-s * CELL / 2 for s in size)
    out = []
    for p in pf['ports']:
        face = cells_of(lo_m, size, p['pos'])
        cell = tuple(face[i] + p['facing'][i] for i in range(3))
        inside = all(0 <= face[i] < size[i] for i in range(3))
        outside = not all(0 <= cell[i] < size[i] for i in range(3))
        out.append(dict(p, face=list(face), cell=list(cell), ok=inside and outside))
    return {'size': size, 'lo_m': lo_m, 'ports': out}


# ---------------------------------------------------------------- placement

def rot(m, q):
    return tuple(sum(m[i][j] * q[j] for j in range(3)) for i in range(3))


def rot_t(m, q):
    return tuple(sum(m[j][i] * q[j] for j in range(3)) for i in range(3))


def frame(size, k):
    w, h, d = size
    m = ORI[k]
    corners = [rot(m, (x, y, z)) for x in (0, w - 1) for y in (0, h - 1) for z in (0, d - 1)]
    mn = tuple(min(c[i] for c in corners) for i in range(3))
    return m, mn


def to_world(size, origin, k, q):
    m, mn = frame(size, k)
    r = rot(m, q)
    return tuple(origin[i] + r[i] - mn[i] for i in range(3))


def to_local(size, origin, k, wq):
    """World cell -> canonical cell of a part placed at origin/orientation k (inverse of to_world)."""
    m, mn = frame(size, k)
    return rot_t(m, tuple(wq[i] - origin[i] + mn[i] for i in range(3)))


def dir_to_local(k, dvec):
    return rot_t(ORI[k], dvec)


def footprint(size, origin, k):
    w, h, d = size
    return {to_world(size, origin, k, (x, y, z)) for x in range(w) for y in range(h) for z in range(d)}


def mirror_port(size, cell, face):
    """Mirrored twin: reflect along local x (dx -> w-1-dx)."""
    w = size[0]
    return [w - 1 - cell[0], cell[1], cell[2]], [w - 1 - face[0], face[1], face[2]]


def placed_ports(entry, origin, k, mirrored=False):
    """{name: (world port cell, world face cell, kind, dir)} for a sensors.json entry."""
    size = entry['size']
    out = {}
    for name, p in entry['ports'].items():
        cell, face = (p['cell'], p['face']) if not mirrored else mirror_port(size, p['cell'], p['face'])
        out[name] = (to_world(size, origin, k, cell), to_world(size, origin, k, face), p['kind'], p['dir'])
    return out


# ---------------------------------------------------------------- corpus

D = os.path.expandvars(r'%USERPROFILE%\AppData\LocalLow\ApproximatelyGames\ApproximatelyUp')
G = r'C:\Program Files (x86)\Steam\steamapps\common\Approximately Up\ApproximatelyUp_Data\StreamingAssets'
W = os.path.join(r'C:\Program Files (x86)\Steam\steamapps\workshop\content', '3904850')
CACHE = os.path.join(os.environ.get('TEMP', '.'), 'au_bp_sensors_corpus1.pkl')


def load_corpus():
    """Same files and de-duplication as tools/bp/corpus.py, but each record keeps its GUID, schema struct hash,
    settings bytes and, for all three cable types, the shape byte.
    -> list of (filename, [ (partHash, (x,y,z), rot, shape|None, guid, structHash, data) ])"""
    if os.path.exists(CACHE):
        return pickle.load(open(CACHE, 'rb'))
    seen, out = set(), []
    files = (glob.glob(D + r'\Blueprints\*.bp') + glob.glob(D + r'\BlueprintsBin\*.bp') + glob.glob(G + r'\*.bp')
             + glob.glob(W + r'\*\*.bp'))
    for f in files:
        b = open(f, 'rb').read()
        schema, parts = bpformat.read(b)
        key = frozenset(x['guid'] for x in parts)
        if key in seen:
            continue
        seen.add(key)
        recs = []
        for x in parts:
            cx, cy, cz, r = bpformat.unpack_cell(x['cell'])
            shape = x['data'][20] if x['part'] in CABLES else None
            recs.append((x['part'], (cx, cy, cz), r, shape, x['guid'], schema[x['schema']]['hash'], x['data']))
        out.append((os.path.basename(f), recs))
    pickle.dump(out, open(CACHE, 'wb'))
    return out


def cable_open(k, shape):
    return {rot(ORI[k], o) for o in OPEN.get(shape, ())}


# ---------------------------------------------------------------- validation

NB6 = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


class Context:
    """Per-blueprint lookups shared by all checks: cable cells, record origins, and the footprints and ports of
    the 43 logic parts (tools/bp/partdb.json via model.py, read-only)."""

    def __init__(self, recs, glass_hashes=()):
        import model                       # shared, read-only
        self.recs = recs
        self.cab = {}                      # cell -> (kind, set of open directions)
        self.origin_at = {}                # cell -> [record index]
        self.logic_occ = {}                # cell -> record index (logic-part footprint cells)
        self.logic_ports = {}              # port cell -> [(face cell, dir, record index)]
        for i, (h, c, k, shape, guid, st, data) in enumerate(recs):
            self.origin_at.setdefault(c, []).append(i)
            if h in CABLES and k in ORI:
                self.cab[c] = (CABLES[h], cable_open(k, shape))
            elif h in model.BY_HASH and k in ORI:
                t, mir = model.BY_HASH[h]
                for q in model.footprint(t, c, k):
                    self.logic_occ[q] = i
                for name, p in model.ports(t, c, k, mir).items():
                    self.logic_ports.setdefault(p['cell'], []).append((p['face'], p['dir'], i))
        self.glass = {i for i, r in enumerate(recs) if r[0] in glass_hashes}


def check_instance(ctx, idx, entry, mirrored, origin, k):
    """Checks one placed part against its blueprint. Returns a dict of observations (see validate)."""
    size = entry['size']
    fp = footprint(size, origin, k)
    pp = placed_ports(entry, origin, k, mirrored)
    by_cf = {(v[0], v[1]): n for n, v in pp.items()}
    obs = {'cable_inside': [], 'logic_inside': set(), 'origins_inside': set(), 'glass_inside': set(),
           'hits': [], 'misses': [], 'direct': [], 'port_state': {}}
    for q in fp:
        if q in ctx.cab:
            obs['cable_inside'].append(to_local(size, origin, k, q))
        if q in ctx.logic_occ:
            obs['logic_inside'].add(ctx.logic_occ[q])
        for j in ctx.origin_at.get(q, ()):
            if j != idx:
                (obs['glass_inside'] if j in ctx.glass else obs['origins_inside']).add(j)
    for f in fp:
        for dv in NB6:
            q = _add(f, dv)
            if q in fp or q not in ctx.cab:
                continue
            kind, opens = ctx.cab[q]
            back = (-dv[0], -dv[1], -dv[2])
            if back not in opens:
                continue                    # the cable at q does not open toward this face cell
            name = by_cf.get((q, f))
            lq, lf = to_local(size, origin, k, q), to_local(size, origin, k, f)
            if name is not None:
                obs['hits'].append((name, kind, pp[name][2], q))
            else:
                obs['misses'].append((kind, lq, lf, q))
    for name, (cell, face, kind, d) in pp.items():
        state = 'empty'
        if cell in ctx.cab:
            ck, opens = ctx.cab[cell]
            back = tuple(face[i] - cell[i] for i in range(3))
            state = ('cable-' + ck) if back in opens else 'cable-passing'
        elif cell in ctx.logic_occ:
            state = 'logic-face'
        # direct port-to-port contact: a logic port whose cell is our face cell and whose face is our port cell
        for f2, d2, j in ctx.logic_ports.get(face, ()):
            if f2 == cell:
                state = 'direct-' + d2
                obs['direct'].append((name, d2, j))
        if state == 'empty' and ctx.origin_at.get(cell):
            state = 'other-origin'
        obs['port_state'][name] = state
    return obs


# ---------------------------------------------------------------- settings struct (IL2CPP metadata)

_TYPEDEFS = None


def blueprint_struct(cls):
    """Settings struct a part class serializes with: the nearest class in its inheritance chain that declares a
    nested 'Blueprint' type (global-metadata.dat via tools/bp/il2cpp.py, read-only).
    -> ('<Class>+Blueprint+BlueprintData', [chain of class names])"""
    global _TYPEDEFS
    import il2cpp
    if _TYPEDEFS is None:
        meta = il2cpp.Metadata()
        b = meta.b
        t_off, _, t_count = struct.unpack_from('<3I', b, 8 + 12 * il2cpp.TYPEDEFS)
        tds = []
        for ti in range(t_count):
            o = t_off + 76 * ti
            # v39 record: name (i32), namespace (i32), then u16 byval type, u16 declaring type, u16 parent type
            tds.append((meta.string(struct.unpack_from('<i', b, o)[0]),) + struct.unpack_from('<HHH', b, o + 8))
        by_byval = {}
        for i, t in enumerate(tds):
            by_byval.setdefault(t[1], i)
        has_bp = {t[2] for t in tds if t[0] == 'Blueprint' and t[2] != 0xffff}
        _TYPEDEFS = (tds, by_byval, has_bp)
    tds, by_byval, has_bp = _TYPEDEFS
    idx = next((i for i, t in enumerate(tds) if t[0] == cls), None)
    chain = []
    while idx is not None:
        name, byval, decl, parent = tds[idx]
        chain.append(name)
        if byval in has_bp:
            return name + '+Blueprint+BlueprintData', chain
        idx = by_byval.get(parent)
    return None, chain


def networks(ctx, extra_ports):
    """Cable networks of one blueprint and the ports they join.
    extra_ports: [(owner, port name, port cell, face cell, dir, kind)] for non-logic parts (the sensors).
    Cells join when both open toward each other and are the same cable kind; a port joins when the cable in its
    port cell opens toward its face cell. -> list of networks, each a list of (owner, port name, dir, kind)."""
    comp, cid = {}, 0
    for c in ctx.cab:
        if c in comp:
            continue
        comp[c] = cid
        stack = [c]
        while stack:
            q = stack.pop()
            kind, opens = ctx.cab[q]
            for d in opens:
                n = _add(q, d)
                if n in ctx.cab and n not in comp and ctx.cab[n][0] == kind and (-d[0], -d[1], -d[2]) in ctx.cab[n][1]:
                    comp[n] = cid
                    stack.append(n)
        cid += 1
    nets = {}

    def attach(owner, name, cell, face, d, kind):
        if cell in ctx.cab:
            ck, opens = ctx.cab[cell]
            if tuple(face[i] - cell[i] for i in range(3)) in opens:
                nets.setdefault(comp[cell], []).append((owner, name, d, kind if kind == ck else kind + '!'))

    for cell, lst in ctx.logic_ports.items():
        for face, d, j in lst:
            attach(('logic', j), '?', cell, face, d, 'data')
    for owner, name, cell, face, d, kind in extra_ports:
        attach(owner, name, cell, face, d, kind)
    return list(nets.values())
