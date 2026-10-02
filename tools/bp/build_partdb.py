"""Builds tools/bp/partdb.json: everything the blueprint generator needs per simulator block.

Per type_id: part hash, settings-struct hash, size [w, h, d] in cells, and each named port's
cell (relative to the origin, in the canonical frame = orientation 16) and direction.

Rules (derived in NOTES.md):
  * footprint [0,w) x [0,1) x [0,2); origin = min corner; inputs/outputs sit in the cell just
    outside the back (z = -1) or front (z = 2) face
  * the game numbers ports back face first, then front face, each in ascending x
  * port names and directions come from engine.js (TYPES[t].order / inputs / outputs) and are
    cross-checked against the corpus wiring (an input is always wired to an output)
"""
import json, os, subprocess, sys, collections
sys.path.insert(0, os.path.dirname(__file__))

HERE = os.path.dirname(os.path.abspath(__file__))
# Parts taller than 1 cell (from "rosetta M": flipped upside down, their origin drops by height - 1)
TALL = {'data_hub': 2, 'wireless_transmitter': 2}
ROOT = os.path.dirname(os.path.dirname(HERE))


def engine_types():
    script = ("const {TYPES}=require('./engine.js');const o={};"
              "for(const[t,d] of Object.entries(TYPES))o[t]={order:d.order||null,inputs:d.inputs,outputs:d.outputs};"
              "process.stdout.write(JSON.stringify(o));")
    return json.loads(subprocess.check_output(['node', '-e', script], cwd=ROOT))


def main(check=True):
    import hashes
    res = json.load(open(os.path.join(HERE, 'parts.json'), encoding='utf-8'))
    prefabs = json.load(open(os.path.join(HERE, 'prefabs.json'), encoding='utf-8'))
    types = engine_types()
    path = os.path.join(HERE, 'partdb.json')
    old = json.load(open(path, encoding='utf-8')) if os.path.exists(path) else {}   # keeps twin hashes
    db = {}
    for t, v in res.items():
        cells = sorted(v['ports'], key=lambda q: (0 if q[2] < 0 else 1, q[0]))
        e = types[t]
        order = e['order'] or (e['inputs'] + e['outputs'])
        if t == 'wireless_transmitter':
            order = ['tx']
        if len(order) != len(cells):
            raise SystemExit(f'{t}: {len(order)} named ports, {len(cells)} cells')
        ports = {}
        for name, q in zip(order, cells):
            d = 'both' if t == 'wireless_transmitter' else 'in' if name in e['inputs'] else 'out'
            ports[name] = {'cell': q, 'dir': d}
        if t == 'wireless_transmitter':
            ports['rx'] = dict(ports['tx'])
        w, depth = v['size_xz']
        height = TALL.get(t, 1)
        db[t] = {'name': v['name'], 'hash': v['hash'], 'schema_hash': v['schema_hash'],
                 'size': [w, height, depth], 'ports': ports}
        if old.get(t, {}).get('mirrored_hash'):
            db[t]['mirrored_hash'] = old[t]['mirrored_hash']
        # prefab name: the part hash is AsciiHash64(prefab), the twin's AsciiHash64(prefab + ' M')
        prefab = next(p for p, e in prefabs.items() if e['hash'] == v['hash'])
        db[t]['prefab'] = prefab
        if db[t].get('mirrored_hash', f'{hashes.part_hash(prefab, True):016x}') != f'{hashes.part_hash(prefab, True):016x}':
            raise SystemExit(f'{t}: twin hash does not match {prefab!r} M')

    if check:  # every wired pair in the corpus must join an input to an output
        import networks
        bad = collections.Counter(); good = 0
        dir_of = {(t, i): None for t in res for i in range(len(res[t]['ports']))}
        for t, v in res.items():
            for name, p in db[t]['ports'].items():
                i = v['ports'].index(p['cell'])
                dir_of[(t, i)] = p['dir']
        for nets in networks.networks():
            for net in nets:
                if len(net) != 2: continue
                a, b = (dir_of[k] for k in net)
                if 'both' in (a, b) or {a, b} == {'in', 'out'}: good += 1
                else: bad[tuple(sorted(net))] += 1
        print(f'corpus check: {good} wired pairs join an input to an output; {sum(bad.values())} do not', bad.most_common(5))

    with open(os.path.join(HERE, 'partdb.json'), 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=1)
    for t, v in db.items():
        print(f"{v['name']:20s} {v['size'][0]}x{v['size'][1]}x{v['size'][2]}  " +
              '  '.join(f"{n}{'<' if p['dir']=='in' else '>' if p['dir']=='out' else '<>'}({p['cell'][0]},{p['cell'][2]})" for n, p in v['ports'].items()))


if __name__ == '__main__':
    main(check='--no-check' not in sys.argv)
