"""Independent check of a generated blueprint against the circuit it came from.

    python tools/bp/verify_bp.py <file.bp> <circuit.json>

Re-reads the .bp with bpformat (no shared code with bpgen.js), places every part with model.py
(footprints, twins, orientations) and re-derives the connections with the game's open-face rule
(networks.py): cable cells connect where both open toward each other, a cable joins a port when
the cell in the port's cell opens toward the part, and two ports touching face to face connect.
Then it compares the result with the circuit's wires and reports anything else wrong:
overlaps, cables that open onto nothing, cables over the reach limit, parts that touch nothing.

A flat layout (bpgen opts.flat) sits on a floor of Frame Quarters: the floor holds its parts and its labels (which
lie on it), and a cable's reach is the game's anchoring rule instead of a length: every cell within 10 steps along its
cable of an anchored cell, i.e. one joined to a port or a straight cell lying on a welded frame face.
"""
import collections, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpformat, model
from networks import OPEN

CABLES = {0xe60658e2e04f33ce: 'data', 0x743531fcd428bc2c: 'power', 0xe8f9b8dac4e23b9c: 'plasma'}
# Label and Large Label: plates whose text faces local +z and whose back (local -z) must rest on a part
LABELS = {0x30dd685b29b0b3a1: (2, 1, 1), 0x7cfa59e0d07dcb3e: (4, 1, 1)}
# Frame Quarter (a flat layout's floor): _solidFaces is byte 20, bit 1 = its Y+ face (tools/bp/parts/structure.json)
FRAMES = {0x482074ef572f3723: (4, 4, 4)}
MAX_UNANCHORED = 10


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
    frames, frame_list = {}, []                     # cell -> frame index
    for r in recs:
        x, y, z, k = bpformat.unpack_cell(r['cell'])
        if r['part'] in FRAMES:
            fp = box_footprint(FRAMES[r['part']], (x, y, z), k)
            for c in fp:
                if c in frames:
                    errors.append(f'two frames in cell {c}')
                frames[c] = len(frame_list)
            # welded top face (only the canonical orientation 16 = identity keeps Y+ up; others are not used)
            frame_list.append({'cells': fp, 'top': k == 16 and bool(r['data'][20] >> 1 & 1)})
            continue
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
    for c in frames:
        if c in occupied or c in cables or c in label_cells:
            errors.append(f'overlap with the floor at {c}')
    # every label rests on parts (or the floor): it is one plate held by its back face, so at least half of that face
    # must touch a part (bpgen's free labels are fully backed; its I/O-row labels at least half)
    for lb in labels:
        loose = sum(add(c, lb['back']) not in occupied and add(c, lb['back']) not in frames for c in lb['cells'])
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
                if g['cells'] > 11 and not frames:
                    errors.append(f'stub of {g["cells"]} cells is over the 11-cell reach')
            continue
        if len(g['ports']) != 2:
            errors.append(f'cable network joining {len(g["ports"])} ports')
            continue
        links.append((g['ports'][0], g['ports'][1], g['cells']))
        if g['cells'] > 21 and not frames:
            errors.append(f'cable of {g["cells"]} cells is over the 21-cell reach')
    # on a floor: the anchoring rule. Anchored: a cell joined to a port, or a straight cell (horizontal axis) lying on
    # a frame whose top face is welded
    if frames:
        anchored = set()
        for c, info in cables.items():
            for d in info['open']:
                n = add(c, d)
                if n in occupied and any(pi == occupied[n] and tuple(inw) == d for pi, name, inw in port_at.get(c, [])):
                    anchored.add(c)
            o = sorted(info['open'])
            below = add(c, (0, -1, 0))
            if len(o) == 2 and o[0] == neg(o[1]) and o[0][1] == 0 and below in frames and frame_list[frames[below]]['top']:
                anchored.add(c)
        dist = {c: 0 for c in anchored}
        queue = collections.deque(anchored)
        while queue:
            q = queue.popleft()
            for d in cables[q]['open']:
                n = add(q, d)
                if n in cables and n not in dist and neg(d) in cables[n]['open']:
                    dist[n] = dist[q] + 1
                    queue.append(n)
        far = [c for c in cables if dist.get(c, 99) > MAX_UNANCHORED]
        if far:
            errors.append(f'{len(far)} cable cells are more than {MAX_UNANCHORED} steps from an anchor, e.g. {far[:3]}')
        notes.append(f'floor of {len(frame_list)} frame quarters; farthest cable cell from an anchor: '
                     f'{max(dist.values(), default=0)} steps')
    links += [(a, b, 0) for a, b in contacts]
    # every link must join an output to an input (a Wireless Transmitter's one port, tx and rx, is either: 'both')
    for a, b, n in links:
        da = parts[a[0]]['ports'][a[1]]['dir']; db = parts[b[0]]['ports'][b[1]]['dir']
        if {da, db} != {'in', 'out'} and not ('both' in (da, db) and {da, db} - {'both'} <= {'in', 'out'}):
            errors.append(f'link joins {parts[a[0]]["type"]}.{a[1]} ({da}) and {parts[b[0]]["type"]}.{b[1]} ({db})')
    # structure: parts must touch each other (or rest on the floor, whose frames touch each other)
    holder = dict(occupied)
    for c, fi in frames.items():
        holder[c] = len(parts) + fi
    parent = list(range(len(parts) + len(frame_list)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for c, pi in holder.items():
        for d in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
            q = holder.get(add(c, d))
            if q is not None and q != pi:
                parent[find(pi)] = find(q)
    groups_n = len({find(i) for i in range(len(parts) + len(frame_list))})
    if groups_n > 1:
        errors.append(f'parts form {groups_n} separate groups')
    # compare the type-level netlist with the circuit (instance identity is not stored in a .bp); a Wireless
    # Transmitter's tx and rx are one physical port, compared as 'trx'
    one = lambda t, port: 'trx' if t == 'wireless_transmitter' else port
    by_types = collections.Counter()
    for a, b, n in links:
        pa, pb = parts[a[0]], parts[b[0]]
        if pa['ports'][a[1]]['dir'] == 'in' or pb['ports'][b[1]]['dir'] == 'out':
            a, b, pa, pb = b, a, pb, pa
        by_types[(pa['type'], one(pa['type'], a[1]), pb['type'], one(pb['type'], b[1]))] += 1
    included = {i['id'] for i in circuit['instances'] if i['type_id'] in model.DB}
    want_types = collections.Counter((ta, one(ta, fp), tb, one(tb, tp)) for fi, fp, ti, tp, ta, tb in want if fi in included and ti in included)
    if by_types != want_types:
        errors.append(f'netlist differs: extra {dict(by_types - want_types)} missing {dict(want_types - by_types)}')
    # name plates (a Wireless Transmitter's or a Datameter's own text): the circuit's `label` parameter, else its id, in
    # the game's label characters, at most 15
    def plate(i):
        t = re.sub(r'[^A-Z0-9%+,\-./: ]+', ' ', str((i.get('parameters') or {}).get('label', i['id'])).upper())
        return re.sub(r'\s+', ' ', t).strip()[:15]
    plated = ('wireless_transmitter', 'datameter')
    want_plates = collections.Counter((i['type_id'], plate(i)) for i in circuit['instances']
                                      if i['type_id'] in plated and i['id'] in included)
    got_plates = collections.Counter((p['type'], p['label']) for p in parts if p['type'] in plated)
    if want_plates != got_plates:
        errors.append(f'name plates differ: extra {dict(got_plates - want_plates)} missing {dict(want_plates - got_plates)}')
    elif want_plates:
        notes.append('name plates: ' + ', '.join(f'{t} "{s}"' for (t, s) in sorted(want_plates)))
    # a part the circuit marks visible stands upright with nothing (part, cable or label) above its cells; a plated part
    # is found by its name plate, any other (a Constant) by counting: as many of its type in view as are marked
    above_all = set(occupied) | set(cables) | set(label_cells)
    def in_view(p):
        up = tuple(model.rot(model.ORI[p['k']]['rotation'], (0, 1, 0)))
        columns = {(c[0], c[2]): max(q[1] for q in p['cells'] if (q[0], q[2]) == (c[0], c[2])) for c in p['cells']}
        return up == (0, 1, 0) and not any((c[0], c[2]) in columns and c[1] > columns[(c[0], c[2])] for c in above_all)
    unplated = collections.Counter()
    for i in circuit['instances']:
        if not (i.get('parameters') or {}).get('visible') or i['id'] not in included:
            continue
        if i['type_id'] not in plated:
            unplated[i['type_id']] += 1
            continue
        if any(in_view(p) for p in parts if p['type'] == i['type_id'] and p['label'] == plate(i)):
            notes.append(f'visible {i["type_id"]} "{plate(i)}" stands upright with nothing above it')
        else:
            errors.append(f'visible {i["type_id"]} "{plate(i)}" is not in view (or not found)')
    for t, n in sorted(unplated.items()):
        shown = sum(in_view(p) for p in parts if p['type'] == t)
        if shown < n:
            errors.append(f'{n} visible {t} parts wanted, {shown} in view')
        else:
            notes.append(f'{n} visible {t} parts wanted, {shown} in view')
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
    print('OK: every circuit wire is present exactly once, nothing else connects, all parts touch'
          + (' or rest on the floor, every cable cell is anchored.' if frames else '.'))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2]))
