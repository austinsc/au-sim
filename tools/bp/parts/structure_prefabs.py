"""Geometry of structure prefabs (frames, glass, windows, labels, decoupler) read from prefab_dump.json.

    python structure_prefabs.py [prefab ...]      # prints a summary; default = all structure prefabs

Facts used (see structure.md):
  * Every part's root EPC_SC* component (EPC_SpaceshipComponent base) stores the part size in metres as 3 floats at
    bytes 12..23 of its serialized body; size / 0.125 = footprint in cells (matches all 43 partdb.json sizes).
    The float at 24 is the mass.
  * DOTSColliderBox body = centre f32[3], euler deg f32[3], size f32[3], bevel f32.
  * EPC_Renderer body = local pos f32[3], euler deg f32[3], scale f32[3], ...
  * SpaceshipComponentAreaPoly ("JointsArea*") body = u32, u32, u32 n, n x f32[3] vertices: the faces through which
    the part can attach to neighbours.
  * EPC_SCFrame (and EPC_SCFrameWithPorts / EPC_SCFramePipe) bodies hold the FaceSetupData list: u32 count, then per face
    PPtr meshGappy (i32 fileID, i64 pathID), PPtr meshSolid, f32[3] x 4 vertices, i32 vertex count (76 bytes).
    The face index i is bit i of the blueprint's _solidFaces and the colour slot _col<i>.
  * Ports: children named "Port ..." carry an EPC_Renderer at the centre of the part cell that holds the port, rotated
    so that local +z points out of the part (euler y=180 -> -z, y=90 -> +x, ...).
Prefab local origin = geometric centre of the footprint.
"""
import json, math, os, re, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BP = os.path.dirname(HERE)
DUMP = json.load(open(os.path.join(BP, 'prefab_dump.json'), encoding='utf-8'))['prefabs']
CELL = 0.125
STRUCTURE = re.compile(r'^SC_(Label|Frame|Glass|Window|Decoupler)')


def f32(b, o, n=1):
    v = struct.unpack_from('<%df' % n, b, o)
    return v if n > 1 else v[0]


def root_component(name):
    for c in DUMP[name][0]['components']:
        if c.get('hex') and c['type'].startswith('EPC_S'):
            return c['type'], bytes.fromhex(c['hex'])
    return None, None


def size_cells(name):
    _, b = root_component(name)
    return tuple(int(round(x / CELL)) for x in f32(b, 12, 3))


def mass(name):
    _, b = root_component(name)
    return round(f32(b, 24), 3)


def euler_dir(e, v=(0.0, 0.0, 1.0)):
    """Unity euler (deg; applied Z, then X, then Y) applied to vector v."""
    x, y, z = v
    ax, ay, az = (math.radians(a) for a in e)
    x, y = x * math.cos(az) - y * math.sin(az), x * math.sin(az) + y * math.cos(az)
    y, z = y * math.cos(ax) - z * math.sin(ax), y * math.sin(ax) + z * math.cos(ax)
    x, z = x * math.cos(ay) + z * math.sin(ay), -x * math.sin(ay) + z * math.cos(ay)
    return tuple(int(round(c)) if abs(c - round(c)) < 1e-3 else round(c, 3) for c in (x, y, z))


def pos_to_cell(p, size):
    """Prefab-local position (metres, origin at centre) -> canonical cell index (origin = min corner)."""
    return tuple(int(math.floor((p[i] + size[i] * CELL / 2) / CELL + 1e-6)) for i in range(3))


def ports(name):
    size = size_cells(name)
    out = {}
    for e in DUMP[name]:
        leaf = e['path'].rsplit('/', 1)[-1]
        if not leaf.startswith('Port'):
            continue
        for c in e['components']:
            if c['type'] == 'EPC_Renderer':
                b = bytes.fromhex(c['hex'])
                p, r = f32(b, 0, 3), f32(b, 12, 3)
                face = pos_to_cell(p, size)
                d = euler_dir(r)
                cell = tuple(face[i] + d[i] for i in range(3))
                out[leaf] = {'face': list(face), 'cell': list(cell), 'out_dir': list(d), 'pos_m': [round(x, 5) for x in p],
                             'euler': [round(x, 3) for x in r]}
    return out


def joints(name):
    out = {}
    for e in DUMP[name]:
        for c in e['components']:
            if c['type'] == 'SpaceshipComponentAreaPoly':
                b = bytes.fromhex(c['hex'])
                n = struct.unpack_from('<I', b, 8)[0]
                pts = [tuple(round(x, 5) for x in f32(b, 12 + 12 * i, 3)) for i in range(n)]
                out[e['path'].rsplit('/', 1)[-1]] = pts
    return out


def colliders(name):
    out = []
    for e in DUMP[name]:
        for c in e['components']:
            if c['type'] == 'DOTSColliderBox':
                b = bytes.fromhex(c['hex'])
                v = f32(b, 0, 10)
                out.append({'node': e['path'].rsplit('/', 1)[-1], 'centre': [round(x, 5) for x in v[0:3]],
                            'euler': [round(x, 3) for x in v[3:6]], 'size': [round(x, 5) for x in v[6:9]],
                            'bevel': round(v[9], 4)})
    return out


def frame_faces(name):
    """FaceSetupData list of a frame-type prefab: [{'verts', 'label', 'mesh_gappy', 'mesh_solid'}], or None."""
    t, b = root_component(name)
    if not t or not t.startswith('EPC_SCFrame'):
        return None
    for o in range(100, len(b) - 80, 4):
        n = struct.unpack_from('<I', b, o)[0]
        if not 1 <= n <= 8:
            continue
        ok = True
        faces = []
        for i in range(n):
            e = o + 4 + 76 * i
            if e + 76 > len(b):
                ok = False
                break
            fid0, pid0, fid1, pid1 = struct.unpack_from('<iqiq', b, e)
            nv = struct.unpack_from('<i', b, e + 72)[0]
            vs = [f32(b, e + 24 + 12 * k, 3) for k in range(4)]
            if fid0 != 0 or fid1 != 0 or nv not in (3, 4) or not all(abs(c) <= 0.51 for v in vs for c in v):
                ok = False
                break
            faces.append({'verts': [[round(c, 4) for c in v] for v in vs[:nv]], 'mesh_gappy': pid0, 'mesh_solid': pid1})
        if ok:
            for f in faces:
                f['label'] = face_label(f['verts'], size_cells(name))
            return faces
    return []


def face_label(verts, size):
    """'X+', 'Y-', ... when all vertices lie on one bounding plane of the footprint, else 'slope(n)' with the normal."""
    half = [s * CELL / 2 for s in size]
    for a, ax in enumerate('XYZ'):
        for sgn, s in ((1, '+'), (-1, '-')):
            if all(abs(v[a] - sgn * half[a]) < 1e-3 for v in verts):
                return ax + s
    p, q, r = verts[0], verts[1], verts[2]
    u = [q[i] - p[i] for i in range(3)]
    v = [r[i] - p[i] for i in range(3)]
    n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
    L = math.sqrt(sum(c * c for c in n)) or 1
    return 'slope(%s)' % ','.join('%.2f' % (c / L) for c in n)


def summary(name):
    t, _ = root_component(name)
    return {'prefab': name, 'component': t, 'size': list(size_cells(name)), 'mass': mass(name),
            'joints': joints(name), 'colliders': colliders(name), 'ports': ports(name), 'faces': frame_faces(name)}


if __name__ == '__main__':
    names = sys.argv[1:] or sorted(n for n in DUMP if STRUCTURE.match(n))
    for n in names:
        s = summary(n)
        print(f"== {n}  {s['component']}  size {s['size']}  mass {s['mass']}")
        for k, v in s['joints'].items():
            print('   joint', k, v)
        for c in s['colliders']:
            print('   collider', c)
        for k, v in s['ports'].items():
            print('   port', k, v)
        if s['faces'] is not None:
            for i, f in enumerate(s['faces']):
                print(f'   face{i} {f["label"]:24s} {f["verts"]}')
