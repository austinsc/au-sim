"""Prefab-derived geometry for the propulsion / powered-consumer parts (see propulsion.md).

Reads propulsion_prefabs.json (propulsion_dump.py) and ../prefab_dump.json. Each part's main component
(EPC_SC<Class>) serializes EPC_SpaceshipComponent's fields first; their names and order come from the
IL2CPP metadata (propulsion_meta.py):

  _mirroredVersion (PPtr, 12 B)  _bounds (Vector3)  _mass  _oceanFloatingSetup  _maxTemperature  _colliders[]
  _colliderAirResistant  _scGroup  _scSecondaryGroup  _availableAmount  _inventoryDependency  _boundsCollider
  _defaultPaintableColor  _paintableRenderers[]  _collisionSoundMaterial  _soundObstacleMin  _soundObstacleMax
  _electricPorts[]  _iconTexture2D  _uiPreviewBounds  ...

Decoded here:
  size    _bounds at bytes 12..23 (metres; / 0.125 = cells). Checked on all 43 logic parts (partdb.json).
  ports   _electricPorts: u32 count, then count x 20-byte records
            { float x, y, z : centre of the face cell the port sits on (prefab frame, origin = part centre)
              i32 face      : 0 +x, 1 -x, 2 +y, 3 -y, 4 +z, 5 -z   (the outward side)
              i32 kind      : 0 data in, 1 data out, 2 power, 3 data both (wireless), 4 plasma }
          The table order is the game's port order (Localization SC_<Key>_Port0..N). A table is accepted
          only if every record coincides with a "Port ..." child's EPC_Renderer position whose euler
          rotation turns +z to the same face (and the counts match).
  paint   _defaultPaintableColor, by a sequential parse of the fixed-size base fields (base_layout()).
  exhaust thrusters: EPC_ThrusterBlow (push volume) and EPC_Heat (heat zone) boxes, in canonical cells.

Canonical frame (orientation 16): cell index = (p + size_m / 2) / 0.125 - 0.5 per axis, footprint
[0,w) x [0,h) x [0,d). The port cell is the face cell plus the face normal.
"""
import json, math, os, struct

HERE = os.path.dirname(os.path.abspath(__file__))
FACES = {0: (1, 0, 0), 1: (-1, 0, 0), 2: (0, 1, 0), 3: (0, -1, 0), 4: (0, 0, 1), 5: (0, 0, -1)}
KINDS = {0: ('data', 'in'), 1: ('data', 'out'), 2: ('power', 'both'), 3: ('data', 'both'), 4: ('plasma', 'both')}

_DUMP = None


def dump():
    """prefab name -> node list: propulsion_prefabs.json (incl. " M" twins), plus ../prefab_dump.json
    for every other part (normal prefabs only), so any part's ports can be decoded the same way."""
    global _DUMP
    if _DUMP is None:
        _DUMP = dict(json.load(open(os.path.join(HERE, '..', 'prefab_dump.json'), encoding='utf-8'))['prefabs'])
        _DUMP.update(json.load(open(os.path.join(HERE, 'propulsion_prefabs.json'), encoding='utf-8'))['prefabs'])
    return _DUMP


def euler_forward(ex, ey, ez):
    """Unity: Quaternion.Euler(ex, ey, ez) * Vector3.forward (rotation order Z, X, Y)."""
    rx, ry = math.radians(ex), math.radians(ey)
    # R = Ry * Rx * Rz; Rz leaves +z alone
    v = (0.0, -math.sin(rx), math.cos(rx))                                  # Rx * (0,0,1)
    v = (v[0] * math.cos(ry) + v[2] * math.sin(ry), v[1], -v[0] * math.sin(ry) + v[2] * math.cos(ry))
    return tuple(int(round(c)) for c in v)


def port_nodes(name):
    """[(child name, pos(3), outward unit vector)] for every 'Port ...' child that is only an EPC_Renderer.

    Skips 'Port Input Reverse Mode Button' (thrusters, fans): a clickable toggle with its own collider,
    not a cable port."""
    out = []
    for n in dump()[name]:
        nm = n['path'].split('/')[-1]
        if not nm.startswith('Port') or [c['type'] for c in n['components']] != ['EPC_Renderer']:
            continue
        for c in n['components']:
            if c['type'] == 'EPC_Renderer':
                f = struct.unpack_from('<6f', bytes.fromhex(c['hex']), 0)
                out.append((nm, tuple(round(x, 5) for x in f[:3]), euler_forward(*f[3:6])))
    return out


def main_component(name):
    root = dump()[name][0]
    return root['components'][0]


def _bytes(name):
    return bytes.fromhex(main_component(name)['hex'])


def size_m(name):
    return struct.unpack_from('<3f', _bytes(name), 12)


def size_cells(name):
    return tuple(int(round(s / 0.125)) for s in size_m(name))


def _on_grid(v, half):
    return abs(v) <= half + 1e-6 and abs(v * 16 - round(v * 16)) < 1e-4


def find_port_table(name):
    """-> (offset, [(pos, face, kind)]) of the port table, or (None, []) when the part has no ports."""
    b = _bytes(name)
    half = [s / 2 for s in size_m(name)]
    nodes = port_nodes(name)
    node_set = {(p, v) for _, p, v in nodes}
    for o in range(24, len(b) - 4, 4):
        n = struct.unpack_from('<i', b, o)[0]
        if n != len(nodes) or n == 0:
            continue
        recs = []
        for i in range(n):
            p = o + 4 + 20 * i
            if p + 20 > len(b):
                break
            x, y, z = struct.unpack_from('<3f', b, p)
            f, k = struct.unpack_from('<2i', b, p + 12)
            if not (all(_on_grid(v, h) for v, h in zip((x, y, z), half)) and f in FACES and k in KINDS):
                break
            recs.append(((round(x, 5), round(y, 5), round(z, 5)), f, k))
        if len(recs) == n and {(p, FACES[f]) for p, f, k in recs} == node_set:
            return o, recs
    if nodes:
        raise ValueError(f'{name}: no port table matches its {len(nodes)} Port children')
    return None, []


def base_layout(name):
    """Sequential parse of the fixed-size run of EPC_SpaceshipComponent fields:

      40  _colliders           u32 count n, n x PPtr (12 B)
      +4  _colliderAirResistant, _scGroup, _scSecondaryGroup, _availableAmount (4 x 4 B)
      +16 _inventoryDependency (PPtr), _boundsCollider (4 B)
          _defaultPaintableColor (u32)                          at 76 + 12 n
          _paintableRenderers  u32 count r, r x PPtr
          _collisionSoundMaterial (u32), _soundObstacleMin, _soundObstacleMax (Vector3 each)
          _electricPorts       u32 count, 20-byte records       at 76 + 12 n + 8 + 12 r + 28

    -> {'paint': int, 'ports_offset': int}. For every part with ports, ports_offset equals the table
    find_port_table() locates independently (checked on 261 of 264 dumped prefabs; the glass parts
    and the port frames use other layouts)."""
    b = _bytes(name)
    n = struct.unpack_from('<i', b, 40)[0]
    po = 76 + 12 * n
    paint, r = struct.unpack_from('<2i', b, po)
    return {'paint': paint, 'ports_offset': po + 8 + 12 * r + 28}


def default_paint(name):
    """The prefab's _defaultPaintableColor (the `_col` a freshly placed part gets)."""
    lay = base_layout(name)
    o, recs = find_port_table(name)
    b = _bytes(name)
    if (o is not None and o != lay['ports_offset']) or (o is None and struct.unpack_from('<i', b, lay['ports_offset'])[0] != 0):
        raise ValueError(f'{name}: base field layout does not line up with the port table')
    return lay['paint']


def to_cell(p, name):
    sm = size_m(name)
    c = tuple((p[a] + sm[a] / 2) / 0.125 - 0.5 for a in range(3))
    r = tuple(int(round(v)) for v in c)
    if any(abs(v - q) > 1e-3 for v, q in zip(c, r)):
        raise ValueError(f'{name}: port position {p} is not a cell centre')
    return r


def _box_cells(name, lo, hi):
    """metre box (prefab frame) -> inclusive canonical cell range of the cells it covers."""
    sm = size_m(name)
    a = [int(math.floor((lo[i] + sm[i] / 2) / 0.125 + 1e-6)) for i in range(3)]
    b = [int(math.ceil((hi[i] + sm[i] / 2) / 0.125 - 1e-6)) - 1 for i in range(3)]
    return [a, b]


def exhaust(name):
    """Thrusters/fans: {'blow': cell box, 'heat': [cell boxes], 'dir': exhaust direction} or None.

    EPC_ThrusterBlow = f32 strength, then 4 corner points (start x/y pair at the near plane, the
    far plane) - read as min/max over the points. EPC_Heat = centre(3), euler(3), size(3)."""
    out = {'heat': []}
    for n in dump()[name]:
        for c in n['components']:
            b = bytes.fromhex(c.get('hex', ''))
            if c['type'] == 'EPC_ThrusterBlow' and len(b) >= 56:
                f = struct.unpack_from('<13f', b, 4)
                pts = [f[0:3], f[3:6], f[6:9], f[9:12]]
                lo = [min(p[i] for p in pts) for i in range(3)]
                hi = [max(p[i] for p in pts) for i in range(3)]
                out['blow'] = _box_cells(name, lo, hi)
            if c['type'] == 'EPC_Heat' and len(b) >= 36:
                f = struct.unpack_from('<9f', b, 0)
                cen, sz = f[0:3], f[6:9]
                out['heat'].append(_box_cells(name, [cen[i] - sz[i] / 2 for i in range(3)],
                                              [cen[i] + sz[i] / 2 for i in range(3)]))
    if 'blow' not in out and not out['heat']:
        return None
    w, h, d = size_cells(name)
    dirs = set()
    for box in ([out['blow']] if 'blow' in out else []) + out['heat']:
        (x0, y0, z0), (x1, y1, z1) = box
        for axis, (lo, hi, n) in enumerate(((x0, x1, w), (y0, y1, h), (z0, z1, d))):
            if lo >= n:
                dirs.add(tuple(1 if i == axis else 0 for i in range(3)))
            if hi < 0:
                dirs.add(tuple(-1 if i == axis else 0 for i in range(3)))
    out['dir'] = sorted(dirs)
    return out


def geometry(name):
    """{'size': (w,h,d), 'ports': [ {node, kind, dir, face, cell, normal} ] in game port order}."""
    w, h, d = size_cells(name)
    o, recs = find_port_table(name)
    nodes = {(p, v): nm for nm, p, v in port_nodes(name)}
    ports = []
    for p, f, k in recs:
        face = to_cell(p, name)
        nrm = FACES[f]
        if not (0 <= face[0] < w and 0 <= face[1] < h and 0 <= face[2] < d):
            raise ValueError(f'{name}: face cell {face} outside the footprint')
        cell = tuple(face[a] + nrm[a] for a in range(3))
        kind, dr = KINDS[k]
        ports.append({'node': nodes[(p, nrm)], 'kind': kind, 'dir': dr, 'kind_code': k, 'face_code': f,
                      'face': list(face), 'cell': list(cell), 'normal': list(nrm)})
    return {'size': [w, h, d], 'ports': ports, 'table_offset': o}


if __name__ == '__main__':
    for name in sorted(dump()):
        try:
            g = geometry(name)
        except ValueError as e:
            print('ERROR', e)
            continue
        print(f"{name:48s} {g['size']} paint {default_paint(name)}  " + '; '.join(
            f"{p['node']}[{p['kind']}/{p['dir']}] face {p['face']} -> {p['cell']}" for p in g['ports']))
