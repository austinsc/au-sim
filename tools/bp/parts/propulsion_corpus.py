"""Corpus loader for the propulsion study: like ../corpus.py, but keeps what that cache drops.

  * the shape byte (`_shape`, offset 20 of EPC_SCCable) for all three cable kinds, not only data cables
  * every record's struct hash, and the raw record bytes for non-cable parts (settings defaults)
  * the source file and its .bpmeta name, for citing evidence

Same file set and the same de-duplication (by GUID set) as corpus.py, so instance counts agree.
Read-only on the blueprint folders. Parsing everything takes a few seconds, so there is no cache by
default; set AU_BP_CACHE=<directory> to keep a pickle there.
"""
import glob, json, os, pickle, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import bpformat, corpus

CACHE = os.path.join(os.environ['AU_BP_CACHE'], 'au_bp_propulsion_corpus1.pkl') if os.environ.get('AU_BP_CACHE') else None
_MEM = None
CABLES = {0xe60658e2e04f33ce: 'data', 0x743531fcd428bc2c: 'power', 0xe8f9b8dac4e23b9c: 'plasma'}


def _meta_name(f):
    m = os.path.splitext(f)[0] + '.bpmeta'
    try:
        return json.load(open(m, encoding='utf-8-sig')).get('_name')
    except Exception:
        return None


def load():
    """-> list of blueprints: {'file', 'name', 'schema': [struct hash], 'parts': [part tuples]}

    part tuple = (partHash, (x, y, z), rot, shape, col, structHash, data)
      shape  cable shape byte for any cable kind (0 straight, 1 corner), else None
      data   raw struct bytes for non-cable parts, else None"""
    global _MEM
    if _MEM is not None:
        return _MEM
    if CACHE and os.path.exists(CACHE):
        _MEM = pickle.load(open(CACHE, 'rb'))
        return _MEM
    seen = set(); out = []
    files = (glob.glob(corpus.D + r'\Blueprints\*.bp') + glob.glob(corpus.D + r'\BlueprintsBin\*.bp')
             + glob.glob(corpus.G + r'\*.bp') + glob.glob(corpus.W + r'\*\*.bp'))
    for f in files:
        b = open(f, 'rb').read()
        schema, p = bpformat.read(b)
        key = frozenset(x['guid'] for x in p)
        if key in seen:
            continue
        seen.add(key)
        parts = []
        for x in p:
            cx, cy, cz, r = bpformat.unpack_cell(x['cell'])
            is_cable = x['part'] in CABLES
            fl = x['fields'].get(corpus.F_FLAGS)
            parts.append((x['part'], (cx, cy, cz), r, x['data'][20] if is_cable else None,
                          x['data'][fl[0]] if fl else None, schema[x['schema']]['hash'],
                          None if is_cable else bytes(x['data'])))
        out.append({'file': f, 'name': _meta_name(f), 'schema': [s['hash'] for s in schema], 'parts': parts})
    if CACHE:
        pickle.dump(out, open(CACHE, 'wb'))
    _MEM = out
    return out


if __name__ == '__main__':
    bps = load()
    print(len(bps), 'blueprints,', sum(len(b['parts']) for b in bps), 'parts')
