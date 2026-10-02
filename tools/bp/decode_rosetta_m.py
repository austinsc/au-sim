"""Decodes the in-game 'rosetta M' blueprint: rosetta copied into four stacked layers,
bottom = normal, then mirrored on x, y and z (the user's labels for the game's mirror tool).

For every layer: matches parts to names by row (same method as decode_rosetta), then checks
each cable stub against the port model -- normal parts use partdb ports, twin (mirrored) types
use the same ports reflected along local x. Records twin hashes in partdb.json ('mirrored_hash').
"""
import collections, json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
import bpformat, decode_rosetta as dr, networks

HERE = os.path.dirname(os.path.abspath(__file__))
FRAME = 0x30fe6645d0a002a4


def main():
    spec = json.load(open(os.path.join(HERE, 'rosetta.json'), encoding='utf-8'))
    db = json.load(open(os.path.join(HERE, 'partdb.json'), encoding='utf-8'))
    _, ori = networks.load_model()
    by_hash = {int(v['hash'], 16): t for t, v in db.items()}
    schema, parts = bpformat.read(open(dr.find('rosetta M'), 'rb').read())
    cell = lambda x: bpformat.unpack_cell(x['cell'])

    # layers = the y of each row of parts (labels sit at the same y as their row's parts)
    labels = [x for x in parts if x['part'] == dr.LABEL_SMALL and x['label']]
    layer_ys = sorted({cell(x)[1] for x in labels})
    names = ['normal', 'mirror x', 'mirror y', 'mirror z']
    cables = {cell(x)[:3] for x in parts if x['part'] == dr.CABLE}
    others = [x for x in parts if x['part'] not in (dr.CABLE, dr.LABEL_SMALL)]
    twins = {}
    for li, ly in enumerate(layer_ys):
        lab = {x['label']: cell(x) for x in labels if cell(x)[1] == ly}
        hits = misses = 0; kinds = collections.Counter()
        for row in spec['rows']:
            if row['label'] not in lab: continue
            lx, _, lz, _ = lab[row['label']]
            # parts of this row: within one cell of the label's y and z
            members = [x for x in others if abs(cell(x)[1] - ly) <= 1 and abs(cell(x)[2] - lz) <= 1]
            members.sort(key=lambda x: abs(cell(x)[0] - lx))
            for (name, t), x in zip(row['parts'], members):
                cx, cy, cz, k = cell(x)
                v = db[t]; w, h, d = v['size']
                normal = x['part'] == int(v['hash'], 16)
                kinds['normal type' if normal else 'twin type'] += 1
                if not normal:
                    twins.setdefault(t, set()).add(f"{x['part']:016x}")
                m = ori[k]['rotation']
                rf = [networks.rot(m, (a, c, b)) for a in range(w) for c in range(h) for b in range(d)]
                mn = tuple(min(q[i] for q in rf) for i in range(3))
                for p in v['ports'].values():
                    q = p['cell'] if normal else [w - 1 - p['cell'][0], p['cell'][1], p['cell'][2]]
                    wc = tuple((cx, cy, cz)[a] + networks.rot(m, q)[a] - mn[a] for a in range(3))
                    if wc in cables: hits += 1
                    else: misses += 1
            if len(members) != len(row['parts']):
                print(f"  layer {names[li]}: row {row['label']} has {len(members)} parts, expected {len(row['parts'])}")
        print(f"{names[li]:9s} y={ly:3d}  {dict(kinds)}  port stubs where predicted: {hits}, missing: {misses}")
    for t, hs in twins.items():
        if len(hs) != 1:
            raise SystemExit(f'{t}: more than one twin hash {hs}')
        db[t]['mirrored_hash'] = hs.pop()
    frame_twins = {f"{x['part']:016x}" for x in others if x['part'] not in by_hash and x['part'] != FRAME
                   and x['schema'] == next(y['schema'] for y in parts if y['part'] == FRAME)}
    json.dump(db, open(os.path.join(HERE, 'partdb.json'), 'w', encoding='utf-8'), indent=1)
    print(f'twin hashes recorded for {sum("mirrored_hash" in v for v in db.values())} part types; frame twin: {frame_twins}')
    for t, v in db.items():
        print(f"  {v['name']:22s} {v['hash']}  twin {v.get('mirrored_hash', '-')}")


if __name__ == '__main__':
    main()
