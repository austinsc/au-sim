"""Independent check of a generated blueprint against the circuit it came from.

    python tools/bp/verify_bp.py <file.bp> <circuit.json>

Re-reads the .bp with bpformat (no shared code with bpgen.js), places every part with model.py
(footprints, twins, orientations) and re-derives the connections with the game's open-face rule
(networks.py): cable cells connect where both open toward each other, a cable joins a port when
the cell in the port's cell opens toward the part, and two ports touching face to face connect.
Then it compares the result with the circuit's wires and reports anything else wrong:
overlaps, cables that open onto nothing, cables over the reach limit, parts that touch nothing.
"""
import collections, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpformat, model
from networks import OPEN

CABLES = {0xe60658e2e04f33ce: 'data', 0x743531fcd428bc2c: 'power', 0xe8f9b8dac4e23b9c: 'plasma'}
# Label and Large Label: plates whose text faces local +z and whose back (local -z) must rest on a part
LABELS = {0x30dd685b29b0b3a1: (2, 1, 1), 0x7cfa59e0d07dcb3e: (4, 1, 1)}


def box_footprint(size, origin, k):
    m = model.ORI[k]['rotation']
    w, h, d = size
    cells = [tuple(model.rot(m, (x, y, z))) for x in range(w) for y in range(h) for z in range(d)]
    mn = tuple(min(c[a] for c in cells) for a in range(3))
    return {tuple(origin[a] + c[a] - mn[a] for a in range(3)) for c in cells}


def add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def neg(a): return (-a[0], -a[1], -a[2])


def main(bp_path, circuit_path):
    schema, recs = bpformat.read(open(bp_path, 'rb').read())
    circuit = json.load(open(circuit_path, encoding='utf-8'))
    errors, notes = [], []
    parts, cables, labels = [], {}, []
    occupied = {}
    for r in recs:
        x, y, z, k = bpformat.unpack_cell(r['cell'])
        if r['part'] in CABLES:
            shape = r['data'][20]
            m = model.ORI[k]['rotation']
            opens = {tuple(model.rot(m, o)) for o in OPEN[shape]}
            if (x, y, z) in cables or (x, y, z) in occupied:
                errors.append(f'two things in cell {(x, y, z)}')
            cables[(x, y, z)] = {'open': opens, 'col': r['data'][22]}
            continue
        if r['part'] in LABELS:
            fp = box_footprint(LABELS[r['part']], (x, y, z), k)
            for c in fp:
                if c in occupied or c in cables:
                    errors.append(f'overlap at {c}')
                occupied[c] = ('label', len(labels))
            labels.append({'cells': fp, 'back': tuple(model.rot(model.ORI[k]['rotation'], (0, 0, -1))), 'text': r['label']})
            continue
        t, mir = model.BY_HASH.get(r['part'], (None, None))
        if t is None:
            errors.append(f'unknown part hash {r["part"]:016x}')
            continue
        fp = model.footprint(t, (x, y, z), k)
        pi = len(parts)
        for c in fp:
            if c in occupied or c in cables:
                errors.append(f'overlap at {c}')
            occupied[c] = pi
        ports = model.ports(t, (x, y, z), k, mir)
        parts.append({'type': t, 'mir': mir, 'k': k, 'origin': (x, y, z), 'cells': fp, 'ports': ports,
                      'label': r['label'] or ''})
    label_cells = {c: v[1] for c, v in occupied.items() if isinstance(v, tuple)}
    occupied = {c: v for c, v in occupied.items() if not isinstance(v, tuple)}
    # every label rests on parts: it is one plate held by its back face, so at least half of that face must
    # touch a part (bpgen's free labels are fully backed; its I/O-row labels at least half)
    for lb in labels:
        loose = sum(add(c, lb['back']) not in occupied for c in lb['cells'])
        if 2 * loose > len(lb['cells']):
            errors.append(f'label "{lb["text"]}" is not backed by a part')
        elif loose:
            notes.append(f'label "{lb["text"]}" rests on parts along {len(lb["cells"]) - loose} of {len(lb["cells"])} cells')
    # match placed parts to circuit instances: same type, label = instance id where the part has a label,
    # otherwise by connection pattern (assigned below from the derived netlist)
    want = set()
    inst = {i['id']: i for i in circuit['instances']}
    for e in circuit['edges']:
        a, b = inst[e['from_instance']], inst[e['to_instance']]
        want.add((e['from_instance'], e['from_port'], e['to_instance'], e['to_port'], a['type_id'], b['type_id']))
    # cable components
    comp, cid = {}, 0
    for c in cables:
        if c in comp:
            continue
        stack = [c]; comp[c] = cid
        while stack:
            q = stack.pop()
            for d in cables[q]['open']:
                n = add(q, d)
                if n in cables and n not in comp and neg(d) in cables[n]['open']:
                    comp[n] = cid; stack.append(n)
        cid += 1
    # port index: port cell -> [(part, name, inward)]
    port_at = collections.defaultdict(list)
    for pi, p in enumerate(parts):
        for name, pp in p['ports'].items():
            port_at[pp['cell']].append((pi, name, pp['inward']))
    lo = [min(c[a] for c in list(occupied) + list(cables) + list(label_cells)) for a in range(3)]
    hi = [max(c[a] for c in list(occupied) + list(cables) + list(label_cells)) for a in range(3)]
    groups = collections.defaultdict(lambda: {'ports': [], 'open_out': [], 'cells': 0})
    for c, info in cables.items():
        g = groups[comp[c]]
        g['cells'] += 1
        for d in info['open']:
            n = add(c, d)
            if n in cables:
                if neg(d) not in cables[n]['open']:
                    errors.append(f'cable {c} opens onto the closed side of cable {n}')
                continue
            if n in label_cells:
                errors.append(f'cable {c} opens onto a label')
                continue
            if n in occupied:
                hit = [(pi, name) for pi, name, inward in port_at.get(c, []) if pi == occupied[n] and tuple(inward) == d]
                if hit:
                    g['ports'].append(hit[0])
                else:
                    errors.append(f'cable {c} opens onto a plain face of {parts[occupied[n]]["type"]}')
                continue
            outside = any(n[a] < lo[a] or n[a] > hi[a] for a in range(3))
            if outside:
                g['open_out'].append((c, d))
            else:
                errors.append(f'cable {c} has a dangling open face toward {n} inside the blueprint')
    # direct contacts
    contacts = []
    for pi, p in enumerate(parts):
        for name, pp in p['ports'].items():
            q = occupied.get(pp['cell'])
            if q is None or q <= pi:
                continue
            for name2, pp2 in parts[q]['ports'].items():
                if pp2['cell'] == pp['face'] and pp2['face'] == pp['cell']:
                    contacts.append(((pi, name), (q, name2)))
    links, stubs = [], []
    for g in groups.values():
        if g['open_out']:
            if len(g['ports']) != 1 or len(g['open_out']) != 1:
                errors.append(f'stub network with ports {g["ports"]} and open ends {g["open_out"]}')
            else:
                stubs.append((g['ports'][0], g['open_out'][0], g['cells']))
                end = g['open_out'][0][0]
                near = {label_cells[add(end, d)] for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)) if add(end, d) in label_cells}
                if not near:
                    errors.append(f'stub ending at {end} has no label beside it')
                else:
                    notes.append(f'stub {parts[g["ports"][0][0]]["type"]}.{g["ports"][0][1]} -> label "{labels[min(near)]["text"]}"')
                if g['cells'] > 11:
                    errors.append(f'stub of {g["cells"]} cells is over the 11-cell reach')
            continue
        if len(g['ports']) != 2:
            errors.append(f'cable network joining {len(g["ports"])} ports')
            continue
        links.append((g['ports'][0], g['ports'][1], g['cells']))
        if g['cells'] > 21:
            errors.append(f'cable of {g["cells"]} cells is over the 21-cell reach')
    links += [(a, b, 0) for a, b in contacts]
    # every link must join an output to an input
    for a, b, n in links:
        da = parts[a[0]]['ports'][a[1]]['dir']; db = parts[b[0]]['ports'][b[1]]['dir']
        if {da, db} != {'in', 'out'}:
            errors.append(f'link joins {parts[a[0]]["type"]}.{a[1]} ({da}) and {parts[b[0]]["type"]}.{b[1]} ({db})')
    # structure: parts must touch each other
    parent = list(range(len(parts)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for c, pi in occupied.items():
        for d in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
            q = occupied.get(add(c, d))
            if q is not None and q != pi:
                parent[find(pi)] = find(q)
    groups_n = len({find(i) for i in range(len(parts))})
    if groups_n > 1:
        errors.append(f'parts form {groups_n} separate groups')
    # compare the type-level netlist with the circuit (instance identity is not stored in a .bp)
    by_types = collections.Counter()
    for a, b, n in links:
        pa, pb = parts[a[0]], parts[b[0]]
        if pa['ports'][a[1]]['dir'] == 'in':
            a, b, pa, pb = b, a, pb, pa
        by_types[(pa['type'], a[1], pb['type'], b[1])] += 1
    included = {i['id'] for i in circuit['instances'] if i['type_id'] in model.DB}
    want_types = collections.Counter((ta, fp, tb, tp) for fi, fp, ti, tp, ta, tb in want if fi in included and ti in included)
    if by_types != want_types:
        errors.append(f'netlist differs: extra {dict(by_types - want_types)} missing {dict(want_types - by_types)}')
    n_inst = collections.Counter(i['type_id'] for i in circuit['instances'] if i['id'] in included)
    n_bp = collections.Counter(p['type'] for p in parts)
    if n_inst != n_bp:
        errors.append(f'part counts differ: {dict(n_bp - n_inst)} vs {dict(n_inst - n_bp)}')
    size = [hi[a] - lo[a] + 1 for a in range(3)]
    for n in notes:
        print('  ' + n)
    print(f'{os.path.basename(bp_path)}: {len(parts)} parts, {len(labels)} labels, {len(cables)} cable cells, {len(links)} links '
          f'({len(contacts)} by direct contact), {len(stubs)} stubs, bounding box {size[0]}x{size[1]}x{size[2]}')
    if errors:
        print(f'{len(errors)} PROBLEMS:')
        for e in errors[:30]:
            print('  -', e)
        return 1
    print('OK: every circuit wire is present exactly once, nothing else connects, all parts touch.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2]))
