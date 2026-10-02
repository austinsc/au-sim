"""Placement geometry and settings bytes for the sensor parts (the sensor counterpart of tools/bp/model.py).

Reads only tools/bp/parts/sensors.json (written by validate_sensors.py) and tools/bp/orientations.json, so a
generator can use it without the game files.

    import sensormodel as SM
    SM.footprint('gyro_line', origin, k)            # set of world cells
    SM.ports('gyro_line', origin, k, mirrored)      # {name: {cell, face, inward, dir, kind}}  (as model.ports)
    SM.settings_bytes('velocity_meter', _modeButton=1)   # struct bytes; caller fills _guid (0..15) and _gt (16..19)

Canonical frame = orientation 16: footprint [0,w) x [0,h) x [0,d); a port is the cell just outside the face cell
it belongs to. A mirrored twin (part hash = 'mirrored_hash') has the ports reflected along local x
(dx -> w-1-dx); ports facing +-x then face the other way. After rotating, the origin (the record's CELL) is the
rotated footprint's min corner.
"""
import json, os, struct

HERE = os.path.dirname(os.path.abspath(__file__))
DB = json.load(open(os.path.join(HERE, 'sensors.json'), encoding='utf-8'))
ORI = {int(k): v['rotation'] for k, v in json.load(open(os.path.join(HERE, '..', 'orientations.json'))).items()}
SCHEMAS = json.load(open(os.path.join(HERE, '..', 'schemas.json'), encoding='utf-8'))

BY_HASH = {}                       # part hash -> (key, mirrored?)
for _k, _v in DB.items():
    if _v.get('hash'):
        BY_HASH[int(_v['hash'], 16)] = (_k, False)
    if _v.get('mirrored_hash'):
        BY_HASH[int(_v['mirrored_hash'], 16)] = (_k, True)


def _rot(m, q):
    return tuple(sum(m[i][j] * q[j] for j in range(3)) for i in range(3))


def _frame(key, k):
    w, h, d = DB[key]['size']
    m = ORI[k]
    corners = [_rot(m, (x, y, z)) for x in (0, w - 1) for y in (0, h - 1) for z in (0, d - 1)]
    return m, tuple(min(c[i] for c in corners) for i in range(3))


def footprint(key, origin, k):
    m, mn = _frame(key, k)
    w, h, d = DB[key]['size']
    return {tuple(origin[a] + _rot(m, (x, y, z))[a] - mn[a] for a in range(3))
            for x in range(w) for y in range(h) for z in range(d)}


def ports(key, origin, k, mirrored=False):
    """{name: {'cell': port cell (outside), 'face': footprint cell it touches, 'inward': direction from the port
    cell into the part, 'dir': in/out/both, 'kind': data/power}}"""
    m, mn = _frame(key, k)
    w = DB[key]['size'][0]
    place = lambda q: tuple(origin[a] + _rot(m, q)[a] - mn[a] for a in range(3))
    out = {}
    for name, p in DB[key]['ports'].items():
        cell, face = list(p['cell']), list(p['face'])
        if mirrored:
            cell[0], face[0] = w - 1 - cell[0], w - 1 - face[0]
        pc, fc = place(cell), place(face)
        out[name] = {'cell': pc, 'face': fc, 'inward': tuple(fc[a] - pc[a] for a in range(3)),
                     'dir': p['dir'], 'kind': p['kind']}
    return out


_PACK = {'float': '<f', 'bool': '<B', 'byte': '<B', 'uint32': '<I', 'int32': '<i'}


def settings_bytes(key, **values):
    """The part's settings struct as bytes (size from schemas.json), every setting at its default unless given.
    Each field is written with its true width (a bool declared as 4 B is 1 B; the next field may start inside the
    declared width), so overlapping declarations never clobber each other. _guid and _gt are left zero."""
    e = DB[key]
    b = bytearray(SCHEMAS[e['struct']]['size'])
    for name, f in e['settings'].items():
        v = values.pop(name, f['default'])
        struct.pack_into(_PACK[f['type']], b, f['offset'], int(v) if f['type'] != 'float' else float(v))
    if values:
        raise KeyError(f'{key}: no settings {sorted(values)}')
    return bytes(b)


if __name__ == '__main__':
    # self-check against the validation library: same footprints and ports for every part and orientation
    import sys
    sys.path.insert(0, HERE)
    import sensorlib as S
    n = 0
    for key, e in DB.items():
        if not e.get('prefab'):
            continue
        for k in ORI:
            for mir in (False, True):
                o = (100, 100, 100)
                assert footprint(key, o, k) == S.footprint(e['size'], o, k)
                ref = S.placed_ports(e, o, k, mir)
                got = ports(key, o, k, mir)
                assert all(got[p]['cell'] == ref[p][0] and got[p]['face'] == ref[p][1] for p in ref), (key, k, mir)
                n += 1
        settings_bytes(key)
    print(f'{n} placements agree with sensorlib; settings_bytes ok for all parts')
    print('velocity_meter directional:', settings_bytes('velocity_meter', _modeButton=1).hex())
