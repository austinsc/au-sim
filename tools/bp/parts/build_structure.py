"""Builds tools/bp/parts/structure.json: structure parts (labels, frames, glass, windows, decoupler) for the generator.

    python build_structure.py          # one corpus pass (~2 min), then writes structure.json

Every number comes from the prefab dump (structure_prefabs.py), the corpus (structure_corpus.py) or the
validation passes in this folder; the rules sections are prose written from those results (see structure.md).
The file is written atomically (temp file + rename), so it is valid JSON at all times.
"""
import collections, csv, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BP = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, BP)
import hashes  # noqa: E402
import structure_corpus as sc  # noqa: E402
import structure_geom as g  # noqa: E402
import structure_occupancy as so  # noqa: E402
import structure_prefabs as sp  # noqa: E402

OUT = os.path.join(HERE, 'structure.json')
LOC = r'C:\Program Files (x86)\Steam\steamapps\common\Approximately Up\ApproximatelyUp_Data\StreamingAssets\Localization.csv'
STRUCTURE = re.compile(r'^SC_(Label(Small|Medium)|Frame|Glass|Window|DecouplerQuarter)')
OPEN = {0: ((0, 0, 1), (0, 0, -1)), 1: ((0, 1, 0), (0, 0, 1))}
DIRS = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
KIND = {'SC_DataCable': 'data', 'SC_PowerCable': 'power', 'SC_PlasmaCable': 'plasma'}

# ----------------------------------------------------------------------------------------------- names / structs

def loc_names():
    out = {}
    try:
        for r in csv.reader(open(LOC, encoding='utf-8-sig')):
            if r and r[0].endswith('_Name'):
                out[r[0][:-5]] = r[1]
    except OSError:
        pass
    return out


NAMES = loc_names()
STRUCT_BY_COMPONENT = {'EPC_SCFrame': 'EPC_SCFrame', 'EPC_SCFrameWithPorts': 'EPC_SCFrame', 'EPC_SCFramePipe': 'EPC_SCFrame',
                       'EPC_SCLabel': 'EPC_SCLabel', 'EPC_SpaceshipComponent': 'EPC_SpaceshipComponent',
                       'EPC_SCDecoupler': 'EPC_SpaceshipComponent'}

# ----------------------------------------------------------------------------------------------- ports (prefab)
PORT_TYPES = {0: 'data in', 1: 'data out', 2: 'power', 3: 'data both (wireless)', 4: 'plasma', 5: 'universal (unset)'}
FACE_CODES = {0: '+x', 1: '-x', 2: '+y', 3: '-y', 4: '+z', 5: '-z'}


def port_list(prefab):
    """Ordered port list from the root component: [(child name, face code, type code)], matched to Port renderers."""
    t, b = sp.root_component(prefab)
    ports = sp.ports(prefab)
    if not ports:
        return []
    import struct
    pos = {k: v['pos_m'] for k, v in ports.items()}
    for o in range(0, len(b) - 4, 4):
        cnt = struct.unpack_from('<I', b, o)[0]
        if cnt != len(pos):
            continue
        ents = []
        for i in range(cnt):
            e = o + 4 + 20 * i
            if e + 20 > len(b):
                break
            p = struct.unpack_from('<3f', b, e)
            a, c = struct.unpack_from('<2I', b, e + 12)
            nm = [k for k, q in pos.items() if all(abs(q[j] - p[j]) < 1e-3 for j in range(3))]
            if not nm:
                break
            ents.append((nm[0], a, c))
        if len(ents) == cnt:
            return ents
    return []


# Port naming used in structure.json: side 0 = list indices 0-3, side 1 = indices 4-7, letters A-D as in the game.
def port_key(prefab, child, index):
    if prefab.startswith('SC_FrameQuarterPorts'):
        return 'ABCD'[index % 4] + str(index // 4)
    return child.replace('Port ', '').strip()


def predicted_ports(prefab, mirrored):
    """{key: (port cell, face cell)} in the canonical frame of the placed type (twins reflected on x)."""
    w = sp.size_cells(prefab)[0]
    pr = sp.ports(prefab)
    out = {}
    for i, (child, face_code, typ) in enumerate(port_list(prefab)):
        c, f = list(pr[child]['cell']), list(pr[child]['face'])
        if mirrored:
            c[0], f[0] = w - 1 - c[0], w - 1 - f[0]
        out[port_key(prefab, child, i)] = (tuple(c), tuple(f))
    return out


# ----------------------------------------------------------------------------------------------- solid cells
def hull_planes(points):
    """Planes (unit normal n, offset d; inside: n.p - d <= 0) of the convex hull of a small point set (brute force)."""
    pts = sorted(set(points))
    planes = {}
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            for k in range(j + 1, len(pts)):
                a, b, c = pts[i], pts[j], pts[k]
                u = [b[q] - a[q] for q in range(3)]
                v = [c[q] - a[q] for q in range(3)]
                n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
                L = sum(x * x for x in n) ** 0.5
                if L < 1e-9:
                    continue
                n = tuple(x / L for x in n)
                d = sum(n[q] * a[q] for q in range(3))
                s = [sum(n[q] * p[q] for q in range(3)) - d for p in pts]
                if all(x <= 1e-6 for x in s):
                    key = (tuple(round(x, 4) for x in n), round(d, 4))
                    planes[key] = (n, d)
                elif all(x >= -1e-6 for x in s):
                    key = (tuple(round(-x, 4) for x in n), round(-d, 4))
                    planes[key] = (tuple(-x for x in n), -d)
    return list(planes.values())


def solid_cells(prefab):
    """Canonical cells whose centre lies strictly inside / exactly on the boundary of the convex hull of the part's
    face polygons (frames: FaceSetupData; others: JointsArea polygons). -> (inside, boundary) or None for a full box.
    Corpus: other parts use bounding-box cells whose centre is >= 0.5 cell outside the hull, never boundary cells."""
    w, h, d = sp.size_cells(prefab)
    if not re.match(r'SC_(Frame|Glass|Window|Decoupler)', prefab):
        return None
    faces = sp.frame_faces(prefab)
    if faces:
        polys = [f['verts'] for f in faces]
    else:
        polys = list(sp.joints(prefab).values())
    if not polys:
        return None
    pts = [tuple(round(v[a] / 0.125 + (w, h, d)[a] / 2, 6) for a in range(3)) for P in polys for v in P]
    planes = hull_planes(pts)
    if not planes:
        return None
    inside, boundary = set(), set()
    for x in range(w):
        for y in range(h):
            for z in range(d):
                c = (x + 0.5, y + 0.5, z + 0.5)
                s = max(sum(n[i] * c[i] for i in range(3)) - dd for n, dd in planes)
                if s < -1e-6:
                    inside.add((x, y, z))
                elif s <= 1e-6:
                    boundary.add((x, y, z))
    if len(inside) == w * h * d:
        return None
    return inside, boundary


# ----------------------------------------------------------------------------------------------- corpus pass
def corpus_pass(prefabs):
    st = {p: collections.defaultdict(collections.Counter) for p in prefabs}
    pred = {(p, m): predicted_ports(p, m) for p in prefabs for m in (False, True)}
    hull = {p: solid_cells(p) for p in prefabs}
    examples = collections.defaultdict(set)
    for bp, placed, occ in so.iter_blueprints():
        cables = {P['origin']: P for P in placed if P['cat'] == 'cable'}
        for P in placed:
            p = P['prefab']
            if p not in st:
                continue
            S = st[p]
            tw = 'twin' if P['mirrored'] else 'normal'
            S['n'][tw] += 1
            S['rot'][P['rot']] += 1
            # overlaps (bounding box) and, for non-box frames, overlaps of the hull cells
            others = collections.Counter()
            hull_hits = collections.Counter()
            hs = hull[p]
            for c in P['cells']:
                js = [j for j in occ[c] if j != P['i']]
                if not js:
                    continue
                for j in js:
                    others[placed[j]['cat']] += 1
                if hs:
                    lc = g.to_local(P['size'], P['origin'], P['rot'], c)
                    if P['mirrored']:
                        lc = (P['size'][0] - 1 - lc[0], lc[1], lc[2])
                    cls = 'inside' if lc in hs[0] else 'boundary' if lc in hs[1] else 'outside'
                    hull_hits[cls] += len(js)
            if others:
                S['overlap']['instances'] += 1
                for k, v in others.items():
                    S['overlap']['cells_' + k] += v
                examples[p].add(bp['name'])
            for k, v in hull_hits.items():
                S['hull_overlap'][k] += v
            # cables opening toward the part: on predicted port cells or not
            pp = pred[(p, P['mirrored'])]
            port_cells = {v[0]: k for k, v in pp.items()}
            for c in P['cells']:
                for dvec in DIRS:
                    q = (c[0] + dvec[0], c[1] + dvec[1], c[2] + dvec[2])
                    if q in P['cells'] or q not in cables:
                        continue
                    C = cables[q]
                    if (-dvec[0], -dvec[1], -dvec[2]) not in {g.dir_world(C['rot'], o) for o in OPEN.get(C['rec']['data'][20], ())}:
                        continue
                    lc = g.to_local(P['size'], P['origin'], P['rot'], q)
                    lf = g.to_local(P['size'], P['origin'], P['rot'], c)
                    if lc in port_cells and pp[port_cells[lc]][1] == lf:
                        S['port_hits'][(port_cells[lc], KIND[C['prefab']])] += 1
                    else:
                        S['cable_misses'][(lc, lf, KIND[C['prefab']])] += 1
    return st, examples


# ----------------------------------------------------------------------------------------------- assembly
def face_table(prefab):
    f = sp.frame_faces(prefab)
    if f is None:
        return None
    return [{'bit': i, 'face': x['label'], 'verts_m': x['verts']} for i, x in enumerate(f)]


def base_entry(p, st, examples):
    pre = sc.PREFABS[p]
    comp, _ = sp.root_component(p)
    S = st[p]
    n = sum(S['n'].values())
    e = {
        'name': NAMES.get(p, p),
        'prefab': p,
        'hash': pre['hash'],
        'mirrored_hash': pre.get('mirrored_hash'),
        'struct': STRUCT_BY_COMPONENT.get(comp, comp),
        'size': list(sp.size_cells(p)),
        'ports': {},
        'settings': {},
        'corpus': {'instances': n, 'instances_twin': S['n']['twin'],
                   'orientations': {str(k): v for k, v in sorted(S['rot'].items())},
                   'ports_confirmed': 'n/a',
                   'overlaps': S['overlap']['instances'],
                   'overlap_cells': {k: v for k, v in S['overlap'].items() if k != 'instances'}},
        'component': comp,
        'mass_kg': sp.mass(p),
    }
    assert hashes.part_hash(p) == int(pre['hash'], 16)
    if pre.get('mirrored_hash'):
        assert hashes.part_hash(p, True) == int(pre['mirrored_hash'], 16)
    if S['overlap']['instances']:
        e['corpus']['overlap_blueprints'] = sorted(examples[p])[:12]
    if S['hull_overlap']:
        e['corpus']['overlap_cells_by_hull_class'] = dict(S['hull_overlap'])
    misses = S['cable_misses']
    if misses:
        e['corpus']['cables_opening_toward_part_off_ports'] = sum(misses.values())
    return e


def frame_settings(p):
    faces = sp.frame_faces(p) or []
    nf = len(faces)
    s = {'_solidFaces': {'default': 0, 'offset': 20, 'bytes': 1,
                         'meaning': 'welded-face bitmask: bit i set = face i (see "faces") carries a welded plate. '
                                    f'This prefab has {nf} faces, so only bits 0..{nf - 1} are ever set (corpus: no '
                                    'value >= 2^faces on any frame type). 0 = bare frame.'}}
    for i in range(8):
        s[f'_col{i}'] = {'default': 200, 'offset': 21 + i, 'bytes': 1,
                         'meaning': (f'paint colour of face {i} ({faces[i]["label"]})' if i < nf else
                                     'unused slot (no such face): always 200') + '; 200 = unpainted'}
    return s


def label_entry(p, base):
    e = base
    w = e['size'][0]
    maxlen = 14 if p == 'SC_LabelSmall' else 16
    e['settings'] = {
        '_actionableLabel': {'default': '', 'offset': 16, 'bytes': 32,
                             'meaning': f'label text, UTF-16LE, zero-padded to 32 bytes. Game _maxLength = {maxlen} '
                                        'characters for this label (EPC_Actionable_Label in the prefab); corpus max '
                                        f'= {maxlen}. Corpus text is upper case only (A-Z 0-9 space and %+,-./:).'},
        '_labelRotated': {'default': 0, 'offset': 53, 'bytes': 1,
                          'meaning': '0 = text upright with its top toward local +y; 1 = text turned 180 deg in the '
                                     'plate (top toward local -y). Older saves (56-byte record) lack the field (= 0). '
                                     'Declared 4 bytes but only byte 53 is the flag; write 0/1 there, zeros after.'},
        '_col': {'default': 0, 'offset': 52, 'bytes': 1, 'meaning': 'paint colour (corpus: 0 most common, then 2)'},
    }
    e['attach'] = {'face': '-z', 'support_cells': [[x, 0, -1] for x in range(w)],
                   'meaning': 'the label is a 0.02 m plate lying against its back face (local -z); its only '
                              'JointsArea is that face, so the cells behind it (local z = -1) must hold the part it '
                              'is mounted on (frame, logic block, ...).'}
    e['text'] = {'faces': '+z', 'up': '+y (or -y when _labelRotated = 1)',
                 'reads_along': '-x (first character at local x = %d end) when _labelRotated = 0; +x when 1' % (w - 1),
                 'max_chars': maxlen}
    return e


DUCTED_FAN_NOTE = ('the only overlaps inside the hull are one SC_DuctedFan design (Hybrid 2 / Pure Atmo 2 / Bad Sub), '
                   'whose fan bounding box runs through these frames')


def generic_notes(p, e):
    """Confidence + notes for parts without hand-written notes in structure_rules.json."""
    c = e['corpus']
    n = c['instances']
    w, h, d = e['size']
    hull = e.get('solid_cells')
    bits = ''
    if e.get('faces'):
        bits = ' Faces/bits: ' + ', '.join(f"{f['bit']} {f['face'] if not f['face'].startswith('slope') else 'slope'}"
                                           for f in e['faces']) + '.'
    twin = ' Mirrored twin exists (reflect x).' if e.get('mirrored_hash') else ' No mirrored twin (symmetric).'
    if not hull:
        conf = 'high' if n >= 5 and c['overlaps'] == 0 else 'medium'
        note = (f'{w}x{h}x{d} box from the prefab size field; fills its whole footprint. {n} corpus instances, '
                f'{c["overlaps"]} overlapping another part.')
        if n < 5:
            note += ' Few corpus instances; size and anchoring follow the general rules.'
    else:
        ins, bnd = len(hull['inside']), len(hull['boundary'])
        hc = c.get('overlap_cells_by_hull_class', {})
        bad = hc.get('inside', 0) + hc.get('boundary', 0)
        conf = 'medium' if n >= 20 else 'low'
        src = 'face polygons' if e.get('faces') else 'JointsArea polygons (the curved surface itself is a convex mesh collider not in the dump)'
        note = (f'{w}x{h}x{d} bounding box, partial shape: {ins} cells inside + {bnd} on the sloped face of the hull of its '
                f'{src} are solid; the other {w * h * d - ins - bnd} bounding-box cells are free. {n} corpus instances; '
                f'{c["overlaps"]} share bounding-box cells with other parts, ')
        if bad == 0:
            note += 'all of them outside the hull.'
        else:
            note += f'{hc.get("outside", 0)} cells outside the hull; {DUCTED_FAN_NOTE}.'
    return {'confidence': conf, 'notes': note + bits + twin}


def write(doc):
    tmp = OUT + '.tmp'
    json.dump(doc, open(tmp, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    json.load(open(tmp, encoding='utf-8'))
    os.replace(tmp, OUT)


def main():
    prefabs = sorted(p for p in sc.PREFABS if STRUCTURE.match(p) and p in sp.DUMP)
    st, examples = corpus_pass(prefabs)
    rules = json.load(open(os.path.join(HERE, 'structure_rules.json'), encoding='utf-8'))
    doc = {'_about': rules['_about']}
    for k in ('label_rules', 'frame_ports_rules', 'frame_support_rules', 'glass_encasing'):
        doc[k] = rules[k]
    # world directions of a label's text for every orientation code (_labelRotated = 0; negate up/reads for 1)
    doc['label_rules']['orientation_table'] = {
        str(k): {'front': list(g.dir_world(k, (0, 0, 1))), 'up': list(g.dir_world(k, (0, 1, 0))),
                 'reads': list(g.dir_world(k, (-1, 0, 0)))} for k in sorted(g.ORI)}
    per_part = rules.get('parts', {})
    for p in prefabs:
        e = base_entry(p, st, examples)
        comp = e['component']
        if p.startswith('SC_Label'):
            e = label_entry(p, e)
        elif comp.startswith('EPC_SCFrame'):
            e['settings'] = frame_settings(p)
            e['faces'] = face_table(p)
        else:
            e['settings'] = {'_col': {'default': 200 if p.startswith(('SC_Glass', 'SC_Window')) else 0, 'offset': 20,
                                      'bytes': 1, 'meaning': 'paint colour; 200 = unpainted (prefab default)'}}
        hs = solid_cells(p)
        if hs:
            e['solid_cells'] = {'inside': sorted(map(list, hs[0])), 'boundary': sorted(map(list, hs[1])),
                                'meaning': 'canonical cells whose centre is inside (or on a sloped face of) the frame '
                                           'polygon hull; the rest of the bounding box is empty space other parts use'}
        # ports
        lst = port_list(p)
        if lst:
            pr = sp.ports(p)
            S = st[p]
            hits = collections.Counter()
            kinds = collections.defaultdict(set)
            for (k, kind), v in S['port_hits'].items():
                hits[k] += v
                kinds[k].add(kind)
            for i, (child, face_code, typ) in enumerate(lst):
                key = port_key(p, child, i)
                d = {5: 'both', 0: 'in', 1: 'out', 3: 'both', 2: 'both', 4: 'both'}[typ]
                kind = {5: 'universal', 0: 'data', 1: 'data', 3: 'data', 2: 'power', 4: 'plasma'}[typ]
                ent = {'cell': pr[child]['cell'], 'face': pr[child]['face'], 'dir': d, 'kind': kind,
                       'index': i, 'prefab_child': child, 'face_code': FACE_CODES[face_code],
                       'type_code': typ, 'corpus_cable_hits': hits[key],
                       'corpus_cable_kinds': sorted(kinds[key])}
                if p.startswith('SC_FrameQuarterPorts'):
                    ent['pair'] = 'ABCD'[i % 4] + str(1 - i // 4)
                e['ports'][key] = ent
            conf = sum(1 for k in e['ports'] if hits[k] > 0)
            e['corpus']['ports_confirmed'] = f'{conf}/{len(e["ports"])}'
            e['corpus']['cable_hits_on_ports'] = sum(hits.values())
            e['corpus']['cable_misses'] = sum(S['cable_misses'].values())
        if p in per_part:
            e.update(per_part[p])
        else:
            e.update(generic_notes(p, e))
        doc[p] = e
    write(doc)
    print('wrote', OUT, len(prefabs), 'parts')


if __name__ == '__main__':
    main()
