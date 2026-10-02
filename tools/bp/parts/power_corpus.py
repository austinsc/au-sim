"""Raw corpus loader for the power/fluid study (read-only; same files and dedup as ../corpus.py).

corpus.load() keeps only the data cable's shape byte. Power and plasma cables (and every
settings struct) need the raw record, so this keeps, per part:
    (partHash, structHash, (x, y, z), rot, data bytes, {fieldName: (offset, size)})
Field names come from ../schemas.json (hash -> name). Cached in the session scratchpad / TEMP.
"""
import glob, os, sys, json, pickle
HERE = os.path.dirname(os.path.abspath(__file__))
BP = os.path.dirname(HERE)
sys.path.insert(0, BP)
import bpformat, hashes, corpus

CACHE = os.path.join(os.environ.get('AU_SCRATCH', os.environ.get('TEMP', '.')), 'au_power_corpus1.pkl')

SCHEMAS = json.load(open(os.path.join(BP, 'schemas.json'), encoding='utf-8'))
FIELD_NAME = {}
for _s in SCHEMAS.values():
    for _n, _o, _z in _s['fields']:
        FIELD_NAME[hashes.field_hash(_n)] = _n
STRUCT_NAME = {int(v['hash'], 16): k.split('+')[0] for k, v in SCHEMAS.items()}
PREFABS = json.load(open(os.path.join(BP, 'prefabs.json'), encoding='utf-8'))
PREFAB_BY_HASH = {}
for _p, _v in PREFABS.items():
    PREFAB_BY_HASH[int(_v['hash'], 16)] = (_p, False)
    if _v.get('mirrored_hash'):
        PREFAB_BY_HASH[int(_v['mirrored_hash'], 16)] = (_p, True)


def files():
    return (glob.glob(corpus.D + r'\Blueprints\*.bp') + glob.glob(corpus.D + r'\BlueprintsBin\*.bp')
            + glob.glob(corpus.G + r'\*.bp') + glob.glob(corpus.W + r'\*\*.bp'))


def load():
    """-> list of (file, [records]); record = (partHash, structHash, (x,y,z), rot, data, fields)."""
    if os.path.exists(CACHE):
        return pickle.load(open(CACHE, 'rb'))
    seen = set(); out = []
    for f in files():
        b = open(f, 'rb').read()
        schema, p = bpformat.read(b)
        key = frozenset(x['guid'] for x in p)
        if key in seen:
            continue
        seen.add(key)
        recs = []
        for x in p:
            cx, cy, cz, r = bpformat.unpack_cell(x['cell'])
            sh = schema[x['schema']]['hash']
            fields = {FIELD_NAME.get(fh, f'{fh:016x}'): v for fh, v in x['fields'].items()}
            recs.append((x['part'], sh, (cx, cy, cz), r, bytes(x['data']), fields))
        out.append((f, recs))
    pickle.dump(out, open(CACHE, 'wb'))
    return out


if __name__ == '__main__':
    c = load()
    print(len(c), 'blueprints', sum(len(r) for _, r in c), 'records')
