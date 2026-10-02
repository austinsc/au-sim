"""Decodes the in-game 'rosetta' reference blueprint (layout in rosetta.json).

Each row starts with a Label reading R<n>; the row's parts follow it in order, all in one
orientation. Prints, and writes to tools/bp/parts.json, for each part: its hash, schema,
origin, orientation, and the cable stubs touching it (relative to its origin).
"""
import json, os, sys, glob, collections
sys.path.insert(0, os.path.dirname(__file__))
import bpformat

HERE = os.path.dirname(os.path.abspath(__file__))
GAME_BP = os.path.expandvars(r'%USERPROFILE%\AppData\LocalLow\ApproximatelyGames\ApproximatelyUp\Blueprints')
CABLE = 0xe60658e2e04f33ce
LABEL_SMALL = 0x30dd685b29b0b3a1

# Copies of the user's 'rosetta' and 'rosetta M' blueprints live in tools/bp/reference (the user removed the
# in-game ones on 2026-10-02); the game folder is searched after them.
REFERENCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reference')

def find(name):
    for d in (REFERENCE, GAME_BP):
        for m in glob.glob(os.path.join(d, '*.bpmeta')):
            if json.load(open(m, encoding='utf-8')).get('_name') == name:
                return m[:-len('.bpmeta')] + '.bp'
    raise SystemExit(f'no blueprint named {name!r}')

def main():
    spec = json.load(open(os.path.join(HERE, 'rosetta.json'), encoding='utf-8'))
    path = find('rosetta')
    schema, parts = bpformat.read(open(path, 'rb').read())
    cell = lambda x: bpformat.unpack_cell(x['cell'])
    labels = {x['label']: x for x in parts if x['part'] == LABEL_SMALL and x['label']}
    cables = [cell(x)[:3] for x in parts if x['part'] == CABLE]
    others = [x for x in parts if x['part'] not in (CABLE, LABEL_SMALL)]

    # connected cable runs
    cs = set(cables); seen = set(); runs = []
    for c in cables:
        if c in seen: continue
        stack = [c]; comp = []
        seen.add(c)
        while stack:
            q = stack.pop(); comp.append(q)
            for d in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)):
                n = (q[0]+d[0], q[1]+d[1], q[2]+d[2])
                if n in cs and n not in seen: seen.add(n); stack.append(n)
        runs.append(comp)

    result = {}
    for row in spec['rows']:
        lab = labels.get(row['label'])
        if not lab:
            print(f"{row['label']}: no label found"); continue
        lx, ly, lz, _ = cell(lab)
        # parts on this row: same y, z within 1 of the label, ordered by distance from the label
        members = [x for x in others if cell(x)[1] == ly and abs(cell(x)[2] - lz) <= 1]
        axis = 0  # rows run along x (checked below)
        members.sort(key=lambda x: abs(cell(x)[axis] - lx))
        if len(members) != len(row['parts']):
            print(f"{row['label']}: found {len(members)} parts, expected {len(row['parts'])}")
            if not members: continue
        for (name, type_id), x in zip(row['parts'], members):
            ox, oy, oz, rot = cell(x)
            result[type_id] = {'name': name, 'hash': f"{x['part']:016x}", 'schema_hash': f"{schema[x['schema']]['hash']:016x}",
                               'origin': [ox, oy, oz], 'rot': rot, 'stubs': []}
    # attach each cable run to the nearest part origin
    origins = {t: tuple(v['origin']) for t, v in result.items()}
    for comp in runs:
        best = min(origins, key=lambda t: min(abs(c[0]-origins[t][0]) + abs(c[1]-origins[t][1]) + abs(c[2]-origins[t][2]) for c in comp))
        o = origins[best]
        rel = sorted((c[0]-o[0], c[1]-o[1], c[2]-o[2]) for c in comp)
        result[best]['stubs'].append(rel)
    json.dump(result, open(os.path.join(HERE, 'parts.json'), 'w', encoding='utf-8'), indent=1)
    for t, v in result.items():
        stubs = '  '.join(str(s[0]) if len(s) == 1 else f'{s[0]}..+{len(s)-1}' for s in sorted(v['stubs']))
        print(f"{v['name']:22s} {v['hash']}  rot {v['rot']:2d}  stubs({len(v['stubs'])}): {stubs}")

if __name__ == '__main__':
    main()
