"""Corpus loader for the structure-part study (frames, glass, windows, labels).

Like tools/bp/corpus.py, but keeps what the structure study needs that corpus.load() drops:
the blueprint name (.bpmeta _name), the source file, each record's struct hash and raw settings bytes.

    import structure_corpus as sc
    for bp in sc.load():           # deduplicated by GUID set, same rule as corpus.py
        bp['name'], bp['file']
        for r in bp['parts']:      # dicts: part, struct, x, y, z, rot, data (bytes), fields {fieldHash: (off, size)}
            ...

Read-only on all game / user folders. The cache lives in %TEMP%.
"""
import glob, json, os, pickle, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BP = os.path.dirname(HERE)
sys.path.insert(0, BP)
import bpformat, hashes  # noqa: E402

D = os.path.expandvars(r'%USERPROFILE%\AppData\LocalLow\ApproximatelyGames\ApproximatelyUp')
G = r'C:\Program Files (x86)\Steam\steamapps\common\Approximately Up\ApproximatelyUp_Data\StreamingAssets'
W = os.path.join(r'C:\Program Files (x86)\Steam\steamapps\workshop\content', '3904850')
CACHE = os.path.join(os.environ.get('TEMP', '.'), 'au_bp_structure_corpus1.pkl')

PREFABS = json.load(open(os.path.join(BP, 'prefabs.json'), encoding='utf-8'))
SCHEMAS = json.load(open(os.path.join(BP, 'schemas.json'), encoding='utf-8'))
# part hash -> (prefab, mirrored)
NAME = {}
for _p, _v in PREFABS.items():
    NAME[int(_v['hash'], 16)] = (_p, False)
    if _v.get('mirrored_hash'):
        NAME[int(_v['mirrored_hash'], 16)] = (_p, True)
STRUCT = {int(v['hash'], 16): k for k, v in SCHEMAS.items()}
FIELD = {}
for _k, _v in SCHEMAS.items():
    for _f in _v['fields']:
        FIELD[hashes.field_hash(_f[0])] = _f[0]

CABLES = {int(PREFABS[n]['hash'], 16): n for n in ('SC_DataCable', 'SC_PowerCable', 'SC_PlasmaCable')}


def files():
    return (glob.glob(D + r'\Blueprints\*.bp') + glob.glob(D + r'\BlueprintsBin\*.bp') + glob.glob(G + r'\*.bp')
            + glob.glob(W + r'\*\*.bp'))


def _meta_name(f):
    m = f[:-3] + '.bpmeta'
    if os.path.exists(m):
        try:
            return json.load(open(m, encoding='utf-8-sig')).get('_name')
        except Exception:
            return None
    return os.path.basename(f)


def load():
    if os.path.exists(CACHE):
        return pickle.load(open(CACHE, 'rb'))
    seen = set()
    out = []
    for f in files():
        b = open(f, 'rb').read()
        schema, parts = bpformat.read(b)
        key = frozenset(x['guid'] for x in parts)
        if key in seen:
            continue
        seen.add(key)
        recs = []
        for x in parts:
            cx, cy, cz, r = bpformat.unpack_cell(x['cell'])
            recs.append({'part': x['part'], 'struct': schema[x['schema']]['hash'], 'x': cx, 'y': cy, 'z': cz,
                         'rot': r, 'data': x['data'], 'fields': x['fields'], 'label': x['label']})
        out.append({'name': _meta_name(f), 'file': f, 'parts': recs})
    pickle.dump(out, open(CACHE, 'wb'))
    return out


def field(rec, name):
    """Raw bytes of a named field of a record, or None."""
    h = hashes.field_hash(name)
    if h not in rec['fields']:
        return None
    o, s = rec['fields'][h]
    return rec['data'][o:o + s]


if __name__ == '__main__':
    bps = load()
    print(len(bps), 'blueprints,', sum(len(b['parts']) for b in bps), 'parts')
