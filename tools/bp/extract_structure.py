"""Meshes and physical properties of the structure parts (frames, glass, windows, decoupler), from the game files.

    python extract_structure.py      -> tools/bp/parts/structure_meshes.json  and  tools/bp/meshes/<prefab>.obj

Sources: the part prefabs' serialized components (prefab_dump.json, made by prefab_dump.py) and the Mesh assets they
reference in globalgamemanagers.assets (read with UnityPy).

Coordinates are in grid cells, measured from the part's minimum corner at orientation code 16 (identity), so a
quarter spans 0..4 on each axis. (Prefab space is metres from the part's centre; 1 cell = 0.125 m.)

Component layouts (field names from global-metadata.dat, in declaration order; see NOTES.md):
  EPC_SpaceshipComponent  _mirroredVersion PPtr | _bounds f32[3] (size, m) | _mass f32 | _oceanFloatingSetup
      {_linearSlowness, _buoyancy} f32[2] | _maxTemperature i32 | _colliders PPtr[] | _colliderAirResistant i32 |
      _scGroup i32 | _scSecondaryGroup i32 | _availableAmount i32 | _inventoryDependency PPtr[] |
      _boundsCollider PPtr | _defaultPaintableColor i32 | _paintableRenderers PPtr[] | _collisionSoundMaterial i32 |
      _soundObstacleMin f32[3] | _soundObstacleMax f32[3] | _electricPorts {f32[3] pos, i32 dir (4 = +z, 5 = -z, the
      generator's DIRS order), i32 type (5 = universal)}[] | _iconTexture2D PPtr |
      _uiPreviewBounds f32[3] | _categories i32 | _customProperties [] | _propertiesMaterial i32 (SpaceshipJointMaterial)
  EPC_SCFrame             (the above) + _faceSetupData FaceSetupData[]: PPtr _meshGappy, PPtr _meshSolid,
      f32[3] _vert0.._vert3, i32 _verts. Face i is weld bit i (_solidFaces) and paint slot _col<i>.
  EPC_Renderer            local pos f32[3] | euler deg f32[3] | scale f32[3] | PPtr mesh | ...
  DOTSColliderConvex      PPtr mesh | centre f32[3] | euler deg f32[3] | scale f32[3] | bevel radius f32
  SpaceshipComponentAreaPoly ("JointsArea*")  u32 joint type | u32 joint material | u32 n | n x f32[3]
"""
import json
import math
import os
import re
import struct

import UnityPy

GAME = r'C:\Program Files (x86)\Steam\steamapps\common\Approximately Up\ApproximatelyUp_Data'
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_JSON = os.path.join(HERE, 'parts', 'structure_meshes.json')
OUT_OBJ = os.path.join(HERE, 'meshes')
CELL = 0.125
PARTS = re.compile(r'^SC_(Frame|Glass|Window|Decoupler)')

# SpaceshipJointExtension (GameAssembly.dll, the class's static constructor): MATERIALS[material] = (strength,
# force distribution); unused slots are zero. Enum values from global-metadata.dat field defaults.
JOINT_MATERIAL = {0: 'Iron', 1: 'Batteries', 4: 'Nano', 5: 'Glass', 255: 'Invalid'}
JOINT_TYPE = {0: 'Normal', 1: 'Pipe', 2: 'PipeDecoupling', 3: 'Decoupler', 4: 'Glass'}
MATERIALS = {0: (800.0, 0.62), 1: (6000.0, 0.54), 4: (2500.0, 0.48), 5: (750.0, 0.94)}
# _maxTemperature codes as the game shows them (the user, 2026-10-02)
MAX_TEMPERATURE_C = {1: 300, 2: 600}
# SpaceshipJointTypeConnections[a * 5 + b]: likely the 0/1 table below (the only 25-float block among the
# compiler-generated array data that fits); not confirmed against the code yet.
TYPE_CONNECTIONS = [[1, 0, 0, 1, 0], [0, 1, 0, 0, 0], [0, 0, 0, 0, 0], [1, 0, 0, 1, 0], [0, 0, 0, 0, 1]]


def f32(b, o, n=1):
    v = struct.unpack_from('<%df' % n, b, o)
    return list(v) if n > 1 else v[0]


def i32(b, o):
    return struct.unpack_from('<i', b, o)[0]


def pptr(b, o):
    return struct.unpack_from('<q', b, o + 4)[0]          # (i32 fileID, i64 pathID): the path id


def euler_matrix(e):
    """Unity euler (deg): Z, then X, then Y. -> 3x3 rotation matrix (rows)."""
    ax, ay, az = (math.radians(a) for a in e)
    cx, sx, cy, sy, cz, sz = math.cos(ax), math.sin(ax), math.cos(ay), math.sin(ay), math.cos(az), math.sin(az)
    rz = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]
    rx = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    ry = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    mul = lambda a, b: [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    return mul(ry, mul(rx, rz))


def transform(v, pos, euler, scale):
    s = [v[i] * scale[i] for i in range(3)]
    m = euler_matrix(euler)
    r = [sum(m[i][k] * s[k] for k in range(3)) for i in range(3)]
    return [r[i] + pos[i] for i in range(3)]


def parse_component(b):
    """EPC_SpaceshipComponent fields, and the byte offset where a subclass's own fields begin."""
    o = 12
    p = {'size_m': f32(b, o, 3)}; o += 12
    p['mass_kg'] = f32(b, o); o += 4
    p['linear_slowness'], p['buoyancy'] = f32(b, o, 2); o += 8
    p['max_temperature_code'] = i32(b, o); o += 4
    n = i32(b, o); o += 4
    p['colliders'] = [pptr(b, o + 12 * k) for k in range(n)]; o += 12 * n
    p['collider_air_resistant'] = i32(b, o); o += 4
    p['sc_group'] = i32(b, o); o += 4
    p['sc_secondary_group'] = i32(b, o); o += 4
    p['available_amount'] = i32(b, o); o += 4
    n = i32(b, o); o += 4                                     # _inventoryDependency: PPtr[]
    p['inventory_dependency'] = [pptr(b, o + 12 * k) for k in range(n)]; o += 12 * n
    p['bounds_collider_mesh'] = pptr(b, o); o += 12
    p['default_paint'] = i32(b, o); o += 4
    n = i32(b, o); o += 4
    p['paintable_renderers'] = n; o += 12 * n
    p['collision_sound_material'] = i32(b, o); o += 4
    p['sound_obstacle_min'] = f32(b, o, 3); o += 12
    p['sound_obstacle_max'] = f32(b, o, 3); o += 12
    n = i32(b, o); o += 4                                     # _electricPorts: f32[3] position, i32 dir, i32 type
    p['electric_ports'] = [{'pos_m': f32(b, o + 20 * k, 3), 'dir': i32(b, o + 20 * k + 12), 'type': i32(b, o + 20 * k + 16)}
                           for k in range(n)]
    o += 20 * n
    o += 12                                                   # _iconTexture2D
    p['ui_preview_bounds'] = f32(b, o, 3); o += 12
    p['categories'] = i32(b, o); o += 4
    n = i32(b, o); o += 4
    if n:
        raise ValueError('non-empty _customProperties: element layout unknown')
    p['joint_material_code'] = i32(b, o); o += 4
    return p, o


def parse_faces(b, o):
    n = i32(b, o); o += 4
    faces = []
    for k in range(n):
        e = o + 76 * k
        verts = [f32(b, e + 24 + 12 * j, 3) for j in range(4)][:i32(b, e + 72)]
        faces.append({'mesh_gappy': pptr(b, e), 'mesh_solid': pptr(b, e + 12), 'verts_m': verts})
    return faces


def to_cells(v, size):
    return [round(v[i] / CELL + size[i] / 2, 4) for i in range(3)]


def sub(a, b): return [a[i] - b[i] for i in range(3)]
def cross(a, b): return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
def dot(a, b): return sum(a[i] * b[i] for i in range(3))
def norm(a):
    L = math.sqrt(dot(a, a)) or 1.0
    return [c / L for c in a]


def polygon_area(verts):
    """Area of a planar polygon (any vertex order around its boundary)."""
    if len(verts) < 3:
        return 0.0
    acc = [0.0, 0.0, 0.0]
    for i in range(1, len(verts) - 1):
        c = cross(sub(verts[i], verts[0]), sub(verts[i + 1], verts[0]))
        acc = [acc[k] + c[k] for k in range(3)]
    return math.sqrt(dot(acc, acc)) / 2


def label_normal(n, size):
    axes = 'XYZ'
    for a in range(3):
        if abs(abs(n[a]) - 1) < 1e-4:
            return axes[a] + ('+' if n[a] > 0 else '-')
    return None


def slope_angles(n):
    """For a sloped face: its angle to each grid plane it is not parallel to (degrees)."""
    out = {}
    for a, ax in enumerate('XYZ'):
        # angle between the face and the plane normal to axis a = 90 - angle between the normals
        out[ax] = round(90 - math.degrees(math.acos(min(1, abs(n[a])))), 2)
    return out


def planar_polygons(verts, tris):
    """Merge coplanar triangles of a convex mesh into polygons: [{'normal', 'verts' (boundary order), 'area'}]."""
    groups = []
    for t in tris:
        a, b, c = (verts[i] for i in t)
        nrm = cross(sub(b, a), sub(c, a))
        if dot(nrm, nrm) < 1e-12:
            continue
        nrm = norm(nrm)
        d = dot(nrm, a)
        for g in groups:
            if dot(g['normal'], nrm) > 0.9999 and abs(g['d'] - d) < 1e-3:
                g['pts'].extend([a, b, c]); g['area'] += polygon_area([a, b, c])
                break
        else:
            groups.append({'normal': nrm, 'd': d, 'pts': [a, b, c], 'area': polygon_area([a, b, c])})
    out = []
    for g in groups:
        uniq = []
        for p in g['pts']:
            if not any(max(abs(p[i] - q[i]) for i in range(3)) < 1e-3 for q in uniq):
                uniq.append(p)
        cen = [sum(p[i] for p in uniq) / len(uniq) for i in range(3)]
        nrm = g['normal']
        ref = norm(sub(uniq[0], cen))
        oth = cross(nrm, ref)
        uniq.sort(key=lambda p: math.atan2(dot(sub(p, cen), oth), dot(sub(p, cen), ref)))
        out.append({'normal': [round(c, 4) for c in nrm], 'verts': [[round(c, 3) for c in p] for p in uniq],
                    'area': round(g['area'], 4)})
    return out


def read_mesh(byid, pid, cache={}):
    if pid in cache:
        return cache[pid]
    from UnityPy.helpers.MeshHelper import MeshHandler
    o = byid.get(pid)
    if o is None or o.type.name != 'Mesh':
        cache[pid] = None
        return None
    mesh = o.read()
    h = MeshHandler(mesh)
    h.process()
    tris = [list(t) for sm in h.get_triangles() for t in sm]
    cache[pid] = {'name': mesh.m_Name, 'verts': [list(v) for v in h.m_Vertices], 'tris': tris}
    return cache[pid]


def main():
    dump = json.load(open(os.path.join(HERE, 'prefab_dump.json'), encoding='utf-8'))['prefabs']
    env = UnityPy.load(os.path.join(GAME, 'globalgamemanagers.assets'))
    byid = {o.path_id: o for o in env.objects}
    os.makedirs(OUT_OBJ, exist_ok=True)
    result = {
        '_about': ('Frames, glass, windows and the decoupler: properties, collider shape, weldable faces and meshes, '
                   'in grid cells from the minimum corner at orientation 16. Written by tools/bp/extract_structure.py.'),
        'joint_materials': {JOINT_MATERIAL[k]: {'code': k, 'strength': s, 'force_distribution': fd} for k, (s, fd) in MATERIALS.items()},
        'joint_types': {v: k for k, v in JOINT_TYPE.items()},
        'joint_type_connections_likely': TYPE_CONNECTIONS,
        'parts': {},
    }
    for name in sorted(n for n in dump if PARTS.match(n)):
        nodes = dump[name]
        root = next(c for c in nodes[0]['components'] if c.get('hex') and c['type'].startswith('EPC_S'))
        b = bytes.fromhex(root['hex'])
        props, tail = parse_component(b)
        size = [int(round(x / CELL)) for x in props['size_m']]
        part = {'component': root['type'], 'size_cells': size, 'mass_kg': round(props['mass_kg'], 4),
                'joint_material': JOINT_MATERIAL.get(props['joint_material_code'], props['joint_material_code'])}
        mat = MATERIALS.get(props['joint_material_code'])
        if mat:
            part['joint_strength'], part['joint_force_distribution'] = mat
        part['max_temperature_c'] = MAX_TEMPERATURE_C.get(props['max_temperature_code'])
        for k in ('linear_slowness', 'buoyancy', 'max_temperature_code', 'sc_group', 'sc_secondary_group', 'categories',
                  'collision_sound_material', 'collider_air_resistant', 'default_paint'):
            part[k] = round(props[k], 4) if isinstance(props[k], float) else props[k]
        part['ui_preview_bounds'] = [round(x, 4) for x in props['ui_preview_bounds']]
        # collider (convex mesh) -> the part's solid shape
        obj = [f'# {name}: grid cells from the minimum corner (orientation 16)']
        vbase = 1

        def emit(group, verts, tris):
            nonlocal vbase
            obj.append(f'o {group}')
            obj.extend(f'v {v[0]} {v[1]} {v[2]}' for v in verts)
            obj.extend('f ' + ' '.join(str(vbase + i) for i in t) for t in tris)
            vbase += len(verts)

        shape = None
        for n in nodes:
            for c in n['components']:
                if c['type'] == 'DOTSColliderConvex':
                    cb = bytes.fromhex(c['hex'])
                    mesh = read_mesh(byid, pptr(cb, 0))
                    if mesh:
                        cen, eul, scl = f32(cb, 12, 3), f32(cb, 24, 3), f32(cb, 36, 3)
                        vs = [to_cells(transform(v, cen, eul, scl), size) for v in mesh['verts']]
                        polys = planar_polygons(vs, mesh['tris'])
                        for pgn in polys:
                            lab = label_normal(pgn['normal'], size)
                            pgn['face'] = lab or 'slope'
                            if not lab:
                                pgn['slope_deg'] = slope_angles(pgn['normal'])
                        shape = {'mesh': mesh['name'], 'bevel_m': round(f32(cb, 48), 4), 'polygons': polys,
                                 'volume_cells': None}
                        emit(f'collider_{mesh["name"]}', vs, mesh['tris'])
                elif c['type'] == 'DOTSColliderBox':
                    cb = bytes.fromhex(c['hex'])
                    shape = shape or {'box': True, 'centre_m': f32(cb, 0, 3), 'size_m': f32(cb, 24, 3)}
        part['shape'] = shape
        # weldable faces (frames)
        if root['type'].startswith('EPC_SCFrame'):
            faces = parse_faces(b, tail)
            total = sum(polygon_area([to_cells(v, size) for v in f['verts_m']]) for f in faces) or 1
            part['faces'] = []
            for i, f in enumerate(faces):
                vc = [to_cells(v, size) for v in f['verts_m']]
                a = polygon_area(vc)
                nrm = norm(cross(sub(vc[1], vc[0]), sub(vc[2], vc[0])))
                entry = {'bit': i, 'face': label_normal(nrm, size) or 'slope', 'verts': vc, 'area_cells': round(a, 4),
                         'surface_fraction': round(a / total, 4)}
                if entry['face'] == 'slope':
                    entry['slope_deg'] = slope_angles(nrm)
                for kind in ('gappy', 'solid'):
                    mesh = read_mesh(byid, f['mesh_' + kind])
                    if mesh:
                        vs = [to_cells(v, size) for v in mesh['verts']]
                        entry[f'mesh_{kind}'] = {'name': mesh['name'], 'verts': vs, 'tris': mesh['tris']}
                        emit(f'face{i}_{kind}_{mesh["name"]}', vs, mesh['tris'])
                part['faces'].append(entry)
        # render meshes (EPC_Renderer carries the real local transform)
        part['render'] = []
        for n in nodes:
            for c in n['components']:
                if c['type'] != 'EPC_Renderer':
                    continue
                rb = bytes.fromhex(c['hex'])
                mesh = read_mesh(byid, pptr(rb, 36))
                if not mesh:
                    continue
                pos, eul, scl = f32(rb, 0, 3), f32(rb, 12, 3), f32(rb, 24, 3)
                vs = [to_cells(transform(v, pos, eul, scl), size) for v in mesh['verts']]
                part['render'].append({'node': n['path'].split('/', 1)[-1], 'mesh': mesh['name'], 'verts': vs, 'tris': mesh['tris']})
                emit(f'render_{mesh["name"]}', vs, mesh['tris'])
        # attachment areas
        part['joint_areas'] = []
        for n in nodes:
            for c in n['components']:
                if c['type'] == 'SpaceshipComponentAreaPoly':
                    ab = bytes.fromhex(c['hex'])
                    t, m, k = struct.unpack_from('<3I', ab, 0)
                    vs = [to_cells(f32(ab, 12 + 12 * j, 3), size) for j in range(k)]
                    part['joint_areas'].append({'node': n['path'].rsplit('/', 1)[-1], 'type': JOINT_TYPE.get(t, t),
                                                'material': JOINT_MATERIAL.get(m, m), 'verts': vs,
                                                'area_cells': round(polygon_area(vs), 4)})
        open(os.path.join(OUT_OBJ, f'{name}.obj'), 'w', encoding='utf-8', newline='\n').write('\n'.join(obj) + '\n')
        result['parts'][name] = part
    json.dump(result, open(OUT_JSON, 'w', encoding='utf-8'), indent=1)
    print(f'{OUT_JSON}: {len(result["parts"])} parts; OBJ files in {OUT_OBJ}')


if __name__ == '__main__':
    main()
