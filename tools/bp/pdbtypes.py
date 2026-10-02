"""Minimal PDB (MSF 7.0) type-stream reader: struct names -> members (name, type, offset).

Reads lib_burst_generated.pdb shipped with the game to recover the source-level layout of
the blueprint structs (EPC_SC<Part>::Blueprint::BlueprintData).
"""
import struct

LF_FIELDLIST, LF_STRUCTURE, LF_MEMBER, LF_ENUM, LF_ENUMERATE = 0x1203, 0x1505, 0x150d, 0x1507, 0x1502
LF_NESTTYPE, LF_STMEMBER, LF_METHOD, LF_ONEMETHOD, LF_BCLASS, LF_VFUNCTAB, LF_INDEX = 0x1510, 0x150e, 0x150f, 0x1511, 0x1400, 0x1409, 0x1404
LF_ARRAY, LF_UNION, LF_CLASS, LF_POINTER, LF_MODIFIER = 0x1503, 0x1506, 0x1504, 0x1002, 0x1001
SIMPLE = {0x0003: 'void', 0x0010: 'sbyte', 0x0020: 'byte', 0x0030: 'bool', 0x0011: 'short', 0x0021: 'ushort',
          0x0012: 'long32', 0x0022: 'ulong32', 0x0013: 'int64', 0x0023: 'uint64', 0x0040: 'float', 0x0041: 'double',
          0x0068: 'int8', 0x0069: 'uint8', 0x0070: 'char', 0x0071: 'wchar', 0x0072: 'int16', 0x0073: 'uint16',
          0x0074: 'int32', 0x0075: 'uint32', 0x0076: 'int64', 0x0077: 'uint64', 0x007a: 'char16', 0x007b: 'char32'}


def _numeric(b, o):
    v = struct.unpack_from('<H', b, o)[0]
    if v < 0x8000: return v, o + 2
    size = {0x8000: ('<b', 1), 0x8001: ('<h', 2), 0x8002: ('<H', 2), 0x8003: ('<i', 4), 0x8004: ('<I', 4),
            0x8009: ('<q', 8), 0x800a: ('<Q', 8)}[v]
    return struct.unpack_from(size[0], b, o + 2)[0], o + 2 + size[1]


def _cstr(b, o):
    e = b.index(b'\x00', o)
    return b[o:e].decode('utf-8', 'replace'), e + 1


def read_streams(path):
    b = open(path, 'rb').read()
    assert b[:32].startswith(b'Microsoft C/C++ MSF 7.00'), 'not an MSF 7.0 PDB'
    bs, _, nblocks, dir_bytes, _, bmap = struct.unpack_from('<6I', b, 32)
    ndir = (dir_bytes + bs - 1) // bs
    dir_blocks = struct.unpack_from(f'<{ndir}I', b, bmap * bs)
    d = b''.join(b[x * bs:(x + 1) * bs] for x in dir_blocks)[:dir_bytes]
    nstreams = struct.unpack_from('<I', d, 0)[0]
    sizes = struct.unpack_from(f'<{nstreams}I', d, 4)
    o = 4 + 4 * nstreams; streams = []
    for sz in sizes:
        if sz == 0xffffffff: streams.append(b''); continue
        nb = (sz + bs - 1) // bs
        blocks = struct.unpack_from(f'<{nb}I', d, o); o += 4 * nb
        streams.append(b''.join(b[x * bs:(x + 1) * bs] for x in blocks)[:sz])
    return streams


def read_types(path):
    tpi = read_streams(path)[2]
    hdr_size, ti_begin, ti_end, rec_bytes = struct.unpack_from('<4I', tpi, 4)
    o = hdr_size; ti = ti_begin; recs = {}
    while o < hdr_size + rec_bytes:
        ln, kind = struct.unpack_from('<HH', tpi, o)
        recs[ti] = (kind, tpi[o + 4:o + 2 + ln])
        o += 2 + ln; ti += 1
    return recs


def type_name(recs, ti):
    if ti < 0x1000: return SIMPLE.get(ti & 0xff, f'simple{ti:#x}') + ('*' if ti & 0x0f00 else '')
    kind, d = recs.get(ti, (None, b''))
    if kind in (LF_STRUCTURE, LF_CLASS):
        _, o = _numeric(d, 18); return _cstr(d, o)[0]
    if kind == LF_UNION:
        _, o = _numeric(d, 8); return _cstr(d, o)[0]
    if kind == LF_ENUM:
        return 'enum ' + _cstr(d, 12)[0]
    if kind == LF_ARRAY:
        elem = struct.unpack_from('<I', d, 0)[0]; n, _ = _numeric(d, 8)
        return f'{type_name(recs, elem)}[{n} bytes]'
    if kind == LF_POINTER: return type_name(recs, struct.unpack_from('<I', d, 0)[0]) + '*'
    if kind == LF_MODIFIER: return type_name(recs, struct.unpack_from('<I', d, 0)[0])
    return f'type{ti:#x}(kind {kind:#x})'


def members(recs, fieldlist_ti):
    kind, d = recs[fieldlist_ti]
    assert kind == LF_FIELDLIST
    o = 0; out = []
    while o < len(d):
        while o < len(d) and d[o] >= 0xf0: o += 1           # padding
        if o >= len(d): break
        k = struct.unpack_from('<H', d, o)[0]
        if k == LF_MEMBER:
            attr, ty = struct.unpack_from('<HI', d, o + 2)
            off, o2 = _numeric(d, o + 8); name, o = _cstr(d, o2)
            out.append((name, ty, off))
        elif k == LF_STMEMBER:
            o = _cstr(d, o + 8)[1]
        elif k == LF_NESTTYPE:
            o = _cstr(d, o + 8)[1]
        elif k == LF_ONEMETHOD:
            attr = struct.unpack_from('<H', d, o + 2)[0]
            o += 8 + (4 if ((attr >> 2) & 7) in (4, 6) else 0); o = _cstr(d, o)[1]
        elif k == LF_METHOD:
            o = _cstr(d, o + 8)[1]
        elif k == LF_ENUMERATE:
            _, o2 = _numeric(d, o + 4); o = _cstr(d, o2)[1]
        elif k in (LF_BCLASS,):
            _, o = _numeric(d, o + 8)
        elif k == LF_VFUNCTAB:
            o += 8
        elif k == LF_INDEX:
            o += 8
        else:
            break
    return out


def structs(recs, name_filter):
    """{name: (size, [(member, type name, offset)])} for complete (non-forward) structs."""
    out = {}
    for ti, (kind, d) in recs.items():
        if kind not in (LF_STRUCTURE, LF_CLASS): continue
        count, props, fl = struct.unpack_from('<HHI', d, 0)
        if props & 0x80: continue                           # forward reference
        size, o = _numeric(d, 16)
        name = _cstr(d, o)[0]
        if not name_filter(name): continue
        out[name] = (size, [(m, type_name(recs, t), off) for m, t, off in members(recs, fl)])
    return out
