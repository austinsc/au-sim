"""Loads every saved blueprint once (parsed + decoded cells) for statistical inference."""
import glob, os, sys, json, pickle
sys.path.insert(0, os.path.dirname(__file__))
import bpformat

D = os.path.expandvars(r'%USERPROFILE%\AppData\LocalLow\ApproximatelyGames\ApproximatelyUp')
G = r'C:\Program Files (x86)\Steam\steamapps\common\Approximately Up\ApproximatelyUp_Data\StreamingAssets'
W = os.path.join(r'C:\Program Files (x86)\Steam\steamapps\workshop\content', '3904850')   # Steam Workshop downloads
CACHE = os.path.join(os.environ.get('TEMP', '.'), 'au_bp_corpus5.pkl')
CABLE = 0xe60658e2e04f33ce
F_FLAGS = 0xa02a12ac78f009a6

def load():
    """-> list of blueprints; each = list of (partHash, (x,y,z), rot, shape, flags).

    shape = the cable cell's first setting byte (0 straight, 1 corner) for cables, else None.
    flags = the `_col` paint byte (hash …09a6) shared by almost every struct, or None.
    Deduplicated by content."""
    if os.path.exists(CACHE):
        return pickle.load(open(CACHE, 'rb'))
    seen = set(); out = []
    files = glob.glob(D + r'\Blueprints\*.bp') + glob.glob(D + r'\BlueprintsBin\*.bp') + glob.glob(G + r'\*.bp') + glob.glob(W + r'\*\*.bp')
    # the user's reference blueprints (rosetta, rosetta M, mirror test), kept here since they were removed from the game folder
    files += glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reference', '*.bp'))
    for f in files:
        b = open(f, 'rb').read()
        _, p = bpformat.read(b)
        key = frozenset(x['guid'] for x in p)
        if key in seen: continue          # BlueprintsBin holds many duplicates/versions
        seen.add(key)
        bp = []
        for x in p:
            cx, cy, cz, r = bpformat.unpack_cell(x['cell'])
            shape = x['data'][20] if x['part'] == CABLE else None
            fl = x['fields'].get(F_FLAGS)
            flags = x['data'][fl[0]] if fl else None
            bp.append((x['part'], (cx, cy, cz), r, shape, flags))
        out.append(bp)
    pickle.dump(out, open(CACHE, 'wb'))
    return out
