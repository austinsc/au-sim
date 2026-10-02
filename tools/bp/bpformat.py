"""Approximately Up .bp reader (reverse-engineered from saved blueprints; see NOTES.md).

File = schema + records, little-endian throughout.
  schema : u32 nTypes, then per type:
             u64 structHash, u32 size, u32 nFields,
             nFields x (u64 fieldHash, u32 offset, u32 size)
  record : u64 partHash, u32 schemaIndex, u32 zero, struct bytes (schema[schemaIndex].size)

Every id is a hash of a name (hashes.py): parts by prefab name, structs by .NET type name,
fields by C# field name. Fields are located through the schema (offsets differ per struct):
  GUID  `_guid`             (16 B)  every struct, offset 0
  CELL  `_gt`               ( 4 B)  packed grid cell + orientation
  LABEL `_actionableLabel`  (32 B)  UTF-16 text, 16 chars, where present
"""
import struct

F_GUID = 0x5a9afb0dddc03646
F_CELL = 0x674a096805f65dc6
F_LABEL = 0x602a2eadf84c5000


def u32(b, o): return struct.unpack_from('<I', b, o)[0]
def u64(b, o): return struct.unpack_from('<Q', b, o)[0]


def read(b):
    o = 0
    n = u32(b, o); o += 4
    schema = []
    for _ in range(n):
        h = u64(b, o); size = u32(b, o + 8); nf = u32(b, o + 12); o += 16
        fields = [(u64(b, o + 16 * i), u32(b, o + 16 * i + 8), u32(b, o + 16 * i + 12)) for i in range(nf)]
        o += 16 * nf
        schema.append({'hash': h, 'size': size, 'fields': fields})
    parts = []
    while o < len(b):
        if o + 16 > len(b):
            raise ValueError(f'trailing {len(b) - o} bytes at {o}')
        ph = u64(b, o); idx = u32(b, o + 8); z = u32(b, o + 12)
        if idx >= len(schema) or z != 0:
            raise ValueError(f'bad record at {o}: idx={idx} z={z}')
        size = schema[idx]['size']
        data = b[o + 16: o + 16 + size]
        if len(data) != size:
            raise ValueError(f'truncated record at {o}')
        fo = {fh: (off, sz) for fh, off, sz in schema[idx]['fields']}
        co = fo[F_CELL][0]
        label = None
        if F_LABEL in fo:
            lo, ls = fo[F_LABEL]
            label = data[lo:lo + ls].decode('utf-16-le').split(chr(0))[0]
        parts.append({'offset': o, 'part': ph, 'schema': idx, 'guid': data[:16].hex(),
                      'cell': data[co:co + 4], 'label': label, 'data': data, 'fields': fo})
        o += 16 + size
    return schema, parts


# ---- writing -----------------------------------------------------------------

def write(schema, parts):
    """Inverse of read(): schema as read, parts as dicts with 'part', 'schema', 'data'."""
    out = bytearray(struct.pack('<I', len(schema)))
    for t in schema:
        out += struct.pack('<QII', t['hash'], t['size'], len(t['fields']))
        for fh, off, sz in t['fields']:
            out += struct.pack('<QII', fh, off, sz)
    for x in parts:
        if len(x['data']) != schema[x['schema']]['size']:
            raise ValueError(f"part {x['part']:016x}: {len(x['data'])} bytes, schema says {schema[x['schema']]['size']}")
        out += struct.pack('<QII', x['part'], x['schema'], 0) + bytes(x['data'])
    return bytes(out)


def with_new_guid(x):
    """Copy of a part with a fresh .NET-order v4 GUID (no part refers to another's GUID)."""
    import uuid
    y = dict(x)
    y['data'] = uuid.uuid4().bytes_le + bytes(x['data'][16:])
    return y


def with_label(x, text):
    """Copy of a part with its 16-character UTF-16 label replaced."""
    if F_LABEL not in x['fields']:
        raise ValueError('part has no label field')
    lo, ls = x['fields'][F_LABEL]
    enc = text.encode('utf-16-le')
    if len(enc) > ls - 2:
        raise ValueError(f'label too long (max {ls // 2 - 1} characters)')
    d = bytearray(x['data'])
    d[lo:lo + ls] = enc + bytes(ls - len(enc))
    y = dict(x); y['data'] = bytes(d); y['label'] = text
    return y


# ---- cells ---------------------------------------------------------------------

def unpack_cell(c):
    """4 packed bytes -> (x, y, z, orientation): 9 + 9 + 9 bits, then a 5-bit orientation index."""
    v = int.from_bytes(c, 'little')
    return v & 511, (v >> 9) & 511, (v >> 18) & 511, v >> 27


def pack_cell(x, y, z, rot):
    for n, v, hi in (('x', x, 511), ('y', y, 511), ('z', z, 511), ('rot', rot, 31)):
        if not 0 <= v <= hi:
            raise ValueError(f'{n}={v} out of range 0..{hi}')
    return (x | (y << 9) | (z << 18) | (rot << 27)).to_bytes(4, 'little')


def with_cell(x, cx, cy, cz, rot):
    """Copy of a part moved to a new cell / orientation."""
    off = x['fields'][F_CELL][0]
    d = bytearray(x['data'])
    d[off:off + 4] = pack_cell(cx, cy, cz, rot)
    y = dict(x); y['data'] = bytes(d); y['cell'] = bytes(d[off:off + 4])
    return y
