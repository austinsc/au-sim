"""Corpus access for controls_displays: like tools/bp/corpus.py (same files, same dedup), but keeps
what the shared loader drops: every record's settings bytes and schema struct, and the shape byte of
all three cable types (data, power, plasma). Cached in %TEMP%; read-only on the blueprint files.

load() -> list of blueprints, each a list of Rec(part, cell(x,y,z), rot, struct, data, fields, src)
"""
import glob, os, sys, pickle, collections

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import bpformat, corpus  # noqa: E402  (shared modules, only read)

_SCRATCH = r'C:\Users\sca\AppData\Local\Temp\claude\C--Users-sca-code-au-sim\38f6350a-85ee-4b42-b81e-1d2ecca6d64e\scratchpad'
CACHE = os.environ.get('CD_CORPUS_CACHE') or os.path.join(
    _SCRATCH if os.path.isdir(_SCRATCH) else os.environ.get('TEMP', '.'), 'au_bp_corpus_cd1.pkl')
CABLES = {0xe60658e2e04f33ce: 'data', 0x743531fcd428bc2c: 'power', 0xe8f9b8dac4e23b9c: 'plasma'}
Rec = collections.namedtuple('Rec', 'part cell rot struct data fields src')


def files():
    D, G, W = corpus.D, corpus.G, corpus.W
    return (glob.glob(D + r'\Blueprints\*.bp') + glob.glob(D + r'\BlueprintsBin\*.bp') + glob.glob(G + r'\*.bp')
            + glob.glob(W + r'\*\*.bp'))


def load():
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
        bp = []
        for x in p:
            cx, cy, cz, r = bpformat.unpack_cell(x['cell'])
            st = schema[x['schema']]['hash']
            fields = {fh: (off, sz) for fh, off, sz in schema[x['schema']]['fields']}
            bp.append(Rec(x['part'], (cx, cy, cz), r, st, bytes(x['data']), fields, os.path.basename(f)))
        out.append(bp)
    pickle.dump(out, open(CACHE, 'wb'))
    return out


def cable_shape(rec):
    """(kind, shape) for a cable record, else None. EPC_SCCable: _shape @20, _type @21, _col @22."""
    k = CABLES.get(rec.part)
    return (k, rec.data[20]) if k else None
