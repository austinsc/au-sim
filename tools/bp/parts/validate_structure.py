"""Independent check of structure.json against the corpus, using only what the file says (as a generator would).

    python validate_structure.py        # prints a table, writes validate_structure_report.json

For every structure-part instance in the 301 corpus blueprints:
  (a) footprint: the part's solid cells (whole box, or 'solid_cells' inside+boundary for partial shapes) placed with
      the orientation table must not overlap any other part's cells. Other parts are taken as their bounding boxes,
      or their own solid cells when they are structure parts with 'solid_cells'. Overlaps involving the deliberate
      encasing glitch (FrameHalfA / GlassHalfA in the encased modules) are counted separately.
  (b) ports: every cable cell that opens toward the part must sit on a listed port cell and touch the listed face
      cell (twins: x reflected). Reported as hits / misses and k/m ports seen.
  (c) labels: the cells behind the label (attach.support_cells) are occupied.
"""
import collections, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import structure_corpus as sc  # noqa: E402
import structure_geom as g  # noqa: E402

DOC = json.load(open(os.path.join(HERE, 'structure.json'), encoding='utf-8'))
PARTS = {k: v for k, v in DOC.items() if k.startswith('SC_')}
BY_HASH = {}
for k, v in PARTS.items():
    BY_HASH[int(v['hash'], 16)] = (k, False)
    if v.get('mirrored_hash'):
        BY_HASH[int(v['mirrored_hash'], 16)] = (k, True)
OPEN = {0: ((0, 0, 1), (0, 0, -1)), 1: ((0, 1, 0), (0, 0, 1))}
CABLES = {int(sc.PREFABS[n]['hash'], 16) for n in ('SC_DataCable', 'SC_PowerCable', 'SC_PlasmaCable')}
ENCASED = ('Universal flight computer', 'Better Than PID', 'MEGA', 'Cruiser', 'Somethin')


def solid_local(entry, mirrored):
    w, h, d = entry['size']
    s = entry.get('solid_cells')
    if s:
        cells = [tuple(c) for c in s['inside'] + s['boundary']]
    else:
        cells = [(x, y, z) for x in range(w) for y in range(h) for z in range(d)]
    if mirrored:
        cells = [(w - 1 - c[0], c[1], c[2]) for c in cells]
    return cells


def place(entry, origin, k, mirrored):
    size = tuple(entry['size'])
    return {g.to_world(size, origin, k, c) for c in solid_local(entry, mirrored)}


def main():
    rep = {k: collections.Counter() for k in PARTS}
    port_seen = {k: set() for k in PARTS}
    for bp in sc.load():
        encased = (bp['name'] or '').startswith(ENCASED)
        occ = collections.defaultdict(list)
        items = []
        cables = {}
        for r in bp['parts']:
            if r['rot'] not in g.ORI:
                continue
            origin = (r['x'], r['y'], r['z'])
            if r['part'] in BY_HASH:
                p, m = BY_HASH[r['part']]
                cells = place(PARTS[p], origin, r['rot'], m)
            elif r['part'] in sc.NAME:
                p, m = sc.NAME[r['part']]
                cells = g.footprint(g.SIZE[p], origin, r['rot'])
            else:
                continue
            i = len(items)
            items.append((p, m, r, cells))
            for c in cells:
                occ[c].append(i)
            if r['part'] in CABLES:
                cables[origin] = {g.dir_world(r['rot'], o) for o in OPEN.get(r['data'][20], ())}
        for i, (p, m, r, cells) in enumerate(items):
            if p not in PARTS:
                continue
            E = PARTS[p]
            R = rep[p]
            R['instances'] += 1
            R['twin_instances'] += m
            others = {j for c in cells for j in occ[c] if j != i}
            if others:
                if encased and p in ('SC_FrameHalfA', 'SC_GlassHalfA', 'SC_LabelSmall', 'SC_LabelMedium'):
                    R['overlap_encasing_glitch'] += 1
                elif any(items[j][0] == 'SC_DuctedFan' for j in others):
                    R['overlap_with_ducted_fan_design'] += 1
                else:
                    R['overlap_other'] += 1
            # ports
            size = tuple(E['size'])
            origin = (r['x'], r['y'], r['z'])
            pcells = {}
            for key, pt in E.get('ports', {}).items():
                c, f = list(pt['cell']), list(pt['face'])
                if m:
                    c[0], f[0] = size[0] - 1 - c[0], size[0] - 1 - f[0]
                pcells[g.to_world(size, origin, r['rot'], tuple(c))] = (key, g.to_world(size, origin, r['rot'], tuple(f)))
            for c in cells:
                for dvec in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                    q = (c[0] + dvec[0], c[1] + dvec[1], c[2] + dvec[2])
                    if q in cells or q not in cables or (-dvec[0], -dvec[1], -dvec[2]) not in cables[q]:
                        continue
                    if q in pcells and pcells[q][1] == c:
                        R['port_hits'] += 1
                        port_seen[p].add(pcells[q][0])
                    elif E.get('ports'):
                        R['port_misses'] += 1
            # labels
            if 'attach' in E:
                sup = [g.to_world(size, origin, r['rot'], tuple(c)) for c in E['attach']['support_cells']]
                n_occ = sum(1 for c in sup if any(j != i for j in occ.get(c, [])))
                R['label_back_fully_supported' if n_occ == len(sup) else
                  'label_back_partly_supported' if n_occ else 'label_back_free'] += 1
    out = {}
    print(f'{"part":28s} {"inst":>6s} {"twin":>5s} {"ovl":>4s} {"glitch":>6s} {"fan":>4s} {"ports":>6s} {"hits":>6s} {"miss":>5s}  labels')
    for p in sorted(rep):
        R = rep[p]
        nports = len(PARTS[p].get('ports', {}))
        ports = f'{len(port_seen[p])}/{nports}' if nports else '-'
        lab = ''
        if 'attach' in PARTS[p]:
            lab = f"full {R['label_back_fully_supported']} part {R['label_back_partly_supported']} free {R['label_back_free']}"
        print(f'{p:28s} {R["instances"]:6d} {R["twin_instances"]:5d} {R["overlap_other"]:4d} {R["overlap_encasing_glitch"]:6d} '
              f'{R["overlap_with_ducted_fan_design"]:4d} {ports:>6s} {R["port_hits"]:6d} {R["port_misses"]:5d}  {lab}')
        out[p] = dict(R)
        out[p]['ports_seen'] = ports
    json.dump(out, open(os.path.join(HERE, 'validate_structure_report.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
