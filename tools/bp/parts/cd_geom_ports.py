"""Game port tables for SC_* prefabs (controls_displays helper).

The root EPC_SC* component of every part prefab serializes its electric ports as
    i32 n, then n x { f32 x, f32 y, f32 z (port node position, metres), i32 facing, i32 type }
facing: 0 +x, 1 -x, 2 +y, 3 -y, 4 +z, 5 -z   (same axes as the grid; checked against the node rotations)
type:   0 data in, 1 data out, 2 power, 3 data both (wireless), 4 plasma, 5 universal (frame pass-through)
The table order is the game's port order (Localization SC_<key>_Port0..N). The table sits at a varying
offset (124..232), so it is found by scanning for a table whose positions equal the "Port ..." nodes.
"""
import math, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cd_prefab as P, cd_geom as G  # noqa: E402

FACING = {0: (1, 0, 0), 1: (-1, 0, 0), 2: (0, 1, 0), 3: (0, -1, 0), 4: (0, 0, 1), 5: (0, 0, -1)}
TYPE = {0: 'data_in', 1: 'data_out', 2: 'power', 3: 'data_both', 4: 'plasma', 5: 'universal'}


def _tables(b, size):
    out = []
    for off in range(0, len(b) - 4, 4):
        n = struct.unpack_from('<i', b, off)[0]
        if not 1 <= n <= 16 or off + 4 + 20 * n > len(b):
            continue
        ents = []
        for i in range(n):
            x, y, z, f, t = struct.unpack_from('<3fii', b, off + 4 + 20 * i)
            if not (0 <= f <= 5 and 0 <= t <= 10):
                break
            if any((not math.isfinite(v)) or abs(v) > s * 0.0625 + 1e-4 or abs(v * 16 - round(v * 16)) > 1e-3
                   for v, s in zip((x, y, z), size)):
                break
            ents.append(((round(x, 4), round(y, 4), round(z, 4)), f, t))
        else:
            out.append((off, ents))
    return out


def port_table(prefab):
    """-> (offset, [(node name, facing code, type code)]) in game port order, or (None, []) if no ports."""
    g = G.geometry(prefab)
    if not g['ports']:
        return None, []
    root = P.nodes(prefab)[0]
    comp = next(c for c in root['components'] if c['type'].startswith('EPC_'))
    b = bytes.fromhex(comp['hex'])
    nodepos = {tuple(round(v, 4) for v in p['pos']): n for n, p in g['ports'].items()}
    good = [(off, e) for off, e in _tables(b, g['size'])
            if len(e) == len(nodepos) and all(p in nodepos for p, _, _ in e)]
    if len(good) != 1:
        raise ValueError(f'{prefab}: {len(good)} candidate port tables')
    off, e = good[0]
    rows = [(nodepos[p], f, t) for p, f, t in e]
    for n, f, t in rows:   # the table's facing must agree with the node's euler rotation
        if FACING[f] != g['ports'][n]['facing']:
            raise ValueError(f'{prefab} {n}: table facing {FACING[f]} != node facing {g["ports"][n]["facing"]}')
    return off, rows
