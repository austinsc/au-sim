"""Derives the sensor parts' geometry, ports and settings from the game's prefabs and validates them on the corpus.

    python sensors_dump.py          (once: dumps twins / extra prefabs -> sensors_prefabs.json)
    python validate_sensors.py      -> tools/bp/parts/sensors.json  (+ a report on stdout)

Per part:
  1. prefab (sensorlib.parse_prefab): footprint = the size field of the main EPC_SC<Class> component (bytes 12..23,
     metres), centred on the prefab origin; ports = the port list baked into the same component (game port order,
     face-cell centre, facing code, type), cross-checked against the "Port ..." renderer children.
  2. names: game port i = Localization SC_<Key>_Port<i> = the simulator's TYPES[type].order[i].
  3. twin: the "<prefab> M" prefab must equal the normal ports reflected along local x (dx -> w-1-dx).
  4. struct: nearest class in the IL2CPP inheritance chain declaring a nested Blueprint (sensorlib.blueprint_struct),
     cross-checked with the struct hash of every corpus record of the part.
  5. corpus (sensorlib.check_instance), per unique placement (GUID, cell, orientation):
       (a) overlaps: cable cells / logic-part cells / other parts' origin cells inside the predicted footprint
       (b) cables next to the footprint that open toward it: hits on predicted port cells (by kind), misses elsewhere
       (c) twins: the same with reflected ports
The output is written after every part, atomically, so sensors.json is always valid JSON.
"""
import collections, csv, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sensorlib as S          # noqa: E402
import hashes                  # noqa: E402  (tools/bp, read-only)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
LOC = r'C:\Program Files (x86)\Steam\steamapps\common\Approximately Up\ApproximatelyUp_Data\StreamingAssets\Localization.csv'
OUT = os.path.join(HERE, 'sensors.json')

# simulator type_id -> game key (prefab = "SC_" + key); None = a sensor-like prefab the simulator lacks
PARTS = [
    ('accelerometer', 'Accelerometer'), ('aerometer', 'Aerometer'), ('altimeter', 'Altimeter'),
    ('atmometer', 'Atmometer'), ('axis_rotometer', 'AxisRotometer'), ('distance_meter', 'DistanceMeter'),
    ('gravitymeter', 'Gravitymeter'), ('inclinometer', 'Inclinometer'), ('massmeter', 'Massmeter'),
    ('rotometer', 'Rotometer'), ('thermometer', 'Thermometer'), ('thermoscan', 'Thermoscan'),
    ('trajectory_curvature_meter', 'TrajectoryCurvatureMeter'), ('velocity_meter', 'VelocityMeter'),
    ('windmeter', 'Windmeter'), ('blue_tank', 'BlueTank'), ('green_tank', 'GreenTank'), ('red_tank', 'RedTank'),
    ('long_range_distance_meter', 'LongRangeDistanceMeter'), ('magnetometer', 'Magnetometer'),
    ('gyro_line', 'GyroLine'), ('space_gps', 'SpaceGPS'), ('space_scanner', 'SpaceScanner'),
    ('fuel_analyzer', 'FuelAnalyzer'),
    (None, 'PipeMeter'), (None, 'NanopipeMeter'), (None, 'BaobaraInterferencemeter'),
]

COL = {'default': 0, 'meaning': 'paint colour index (`_col`, 1 byte); 0 = unpainted/default'}
SETTINGS = {
    'EPC_SpaceshipComponent+Blueprint+BlueprintData': {'_col': COL},
    'EPC_SCVelocityMeter+Blueprint+BlueprintData': {
        '_modeButton': {'default': 0, 'meaning': 'mode button (bool; declared 4 B but 1 B, `_col` follows at 21): 0 = Overall Mode, '
                                   'output = speed |v|; 1 = Directional Mode, output = v . (part +z axis), signed. '
                                   'Decoded from SCTick_VelocityMeter.OwnJob (toggle < 0.5 -> sqrt(vx2+vy2+vz2), '
                                   'else dot with the rotated forward axis). Default 0 = the prefab toggle\'s initial '
                                   'state. Both values common in the corpus.'},
        '_col': COL},
    'EPC_SCTank+Blueprint+BlueprintData': {
        '_actionableValue': {'default': 1.0, 'meaning': 'outlet valve opening, f32 0..1 (EPC_Actionable_Valve: 0 = off/closed, '
                                        '1 = on/open). The valve has no stored initial value, so the in-game default '
                                        'is not known; 1.0 (fully open) is used here. Corpus: blue 0.90-1.00, '
                                        'green 0.096-0.103, i.e. the 90 % blue / 10 % green mix the manual recommends.'},
        '_col': COL},
    'EPC_SCGyroLine+Blueprint+BlueprintData': {
        '_rotKnobValue': {'default': 0.0, 'meaning': 'orientation knob (SCTypeGyroLine._actionableOrientationKnob), f32; corpus '
                                     'values 0, 0.25, 0.75 (quarter steps). Prefab knob default 0.'},
        '_toggle': {'default': 1, 'meaning': 'on/off switch (bool; declared 4 B but 1 B). Prefab toggle initial state 1 = on.'},
        '_col': COL,
        '_degrees': {'default': 40, 'meaning': 'display range in degrees, byte: 40 / 60 / 90 / 180 (4-step "Degrees" knob; '
                                'GyroLineDisplayRange). Corpus: 40 (12x), 60, 90.'}},
    'EPC_SCFuelAnalyzer+Blueprint+BlueprintData': {
        '_knobVal': {'default': 0.0, 'meaning': 'input knob, f32 0..1: the value whose fuel performance is estimated when '
                                '`_mode` = 0. Prefab knob default 0.'},
        '_toggle': {'default': 1, 'meaning': 'on/off switch (bool). Prefab toggle initial state 1 = on.'},
        '_col': COL,
        '_mode': {'default': 0, 'meaning': 'input source (bool): 0 = "Input: Knob" (`_knobVal`), 1 = "Input: Data Port" (port '
                             '`value`, clamped to 0..1). Decoded from SCTick_FuelAnalyzer.OwnJob (mode toggle < 0.5 '
                             '-> knob entity, else the data port). Set 1 when the input port is wired. The declared '
                             'struct is 30 B; bytes 27..29 are padding (corpus shows junk there; write 0).'}},
}


PDB = os.path.join(os.path.dirname(LOC), '..', 'Plugins', 'x86_64', 'lib_burst_generated.pdb')
_PDB_STRUCTS = None
PDB_SIZE = {'byte': 1, 'bool': 1, 'float': 4, 'uint32': 4, 'int32': 4, 'Guid': 16}


def settings_for(st):
    """Settings fields of a struct (all but _guid/_gt): default + meaning (above), offset and declared size from
    schemas.json (what a .bp schema entry says), true type and size from the Burst PDB (what to write)."""
    global _PDB_STRUCTS
    import pdbtypes
    if _PDB_STRUCTS is None:
        recs = pdbtypes.read_types(PDB)
        _PDB_STRUCTS = pdbtypes.structs(recs, lambda n: n.endswith('Blueprint::BlueprintData'))
    schema = json.load(open(os.path.join(S.BP, 'schemas.json'), encoding='utf-8'))[st]
    pdb = {m: (t, off) for m, t, off in _PDB_STRUCTS[st.replace('+', '::')][1]}
    known = SETTINGS.get(st, {})
    out = {}
    for name, off, size in schema['fields']:
        if name in ('_guid', '_gt'):
            continue
        t, poff = pdb[name]
        assert poff == off, (st, name)
        f = dict(known.get(name, COL if name == '_col' else {'default': 0, 'meaning': '?'}))
        f.update({'offset': off, 'type': t, 'size': PDB_SIZE[t], 'declared_size': size})
        out[name] = f
    return out


def joint_faces(pf, geom):
    """'JointsArea*' polygons (SpaceshipComponentAreaPoly) as face rectangles in canonical cells: the faces through
    which the part joins its neighbours ('pipe' = a fuel-pipe joint). Interpretation from the prefab only."""
    size, lo = geom['size'], geom['lo_m']
    out = []
    for name, poly in pf['joints']:
        mn = [min(p[i] for p in poly) for i in range(3)]
        mx = [max(p[i] for p in poly) for i in range(3)]
        ax = [i for i in range(3) if abs(mx[i] - mn[i]) < 1e-6]
        if len(ax) != 1:
            continue
        a = ax[0]
        plane = (mn[a] - lo[a]) / S.CELL
        if abs(plane) < 1e-6:
            sign, layer = -1, 0
        elif abs(plane - size[a]) < 1e-6:
            sign, layer = 1, size[a] - 1
        else:
            out.append({'node': name, 'interior_plane': round(plane, 3)})
            continue
        lo_c = [int(round((mn[i] - lo[i]) / S.CELL)) for i in range(3)]
        hi_c = [int(round((mx[i] - lo[i]) / S.CELL)) - 1 for i in range(3)]
        lo_c[a] = hi_c[a] = layer
        normal = [0, 0, 0]
        normal[a] = sign
        out.append({'normal': normal, 'from': lo_c, 'to': hi_c, 'pipe': 'Pipe' in name})
    return out


def sim_types(ids):
    js = ("const {TYPES}=require('./engine.js');const o={};for(const k of %s)o[k]=TYPES[k]||null;"
          "console.log(JSON.stringify(o));" % json.dumps(ids))
    return json.loads(subprocess.run(['node', '-e', js], cwd=ROOT, capture_output=True, text=True, check=True).stdout)


def localization():
    out = {}
    with open(LOC, encoding='utf-8') as f:
        for row in csv.reader(f):
            if len(row) > 1:
                out[row[0]] = row[1]
    return out


def prefab_twin_check(pf_n, pf_m, geom):
    """True if the twin prefab's baked ports are the normal ports reflected along x (dx -> w-1-dx)."""
    w = geom['size'][0]
    bn = S.baked_ports(pf_n['body'], pf_n['ports'])
    bm = S.baked_ports(pf_m['body'], pf_m['ports'])
    if pf_m['size_m'] != pf_n['size_m'] or len(bn) != len(bm):
        return False
    for (pn, cn, tn), (pm, cm, tm) in zip(bn, bm):
        fn, fm = S.cells_of(geom['lo_m'], geom['size'], pn), S.cells_of(geom['lo_m'], geom['size'], pm)
        dn, dm = S.FACING[cn], S.FACING[cm]
        if tn != tm or fm != (w - 1 - fn[0], fn[1], fn[2]) or dm != (-dn[0], dn[1], dn[2]):
            return False
    return True


def build_entry(type_id, key, P, T, L):
    prefab = 'SC_' + key
    name = L.get(prefab + '_Name')
    sim = T.get(type_id) if type_id else None
    if prefab not in P:
        return {'name': name, 'description': L.get(prefab + '_Desc'), 'prefab': None, 'hash': None, 'mirrored_hash': None, 'struct': None, 'size': None,
                'ports': {}, 'settings': {}, 'corpus': {'instances': 0, 'ports_confirmed': '0/0', 'overlaps': 0},
                'confidence': 'low', 'substitute': 'axis_rotometer',
                'notes': ('No "%s" prefab exists in this game build (globalgamemanagers.assets has SC_AxisRotometer '
                          'and SC_AxisRotometer M only); hash %016x never occurs in the corpus. The Localization '
                          'rows remain. Its class EPC_SCRotometer is what SC_AxisRotometer uses, so the Axis '
                          'Rotometer appears to be its in-game replacement: substitute axis_rotometer.'
                          % (prefab, hashes.part_hash(prefab)))}, None
    pf = S.parse_prefab(P[prefab])
    geom = S.derive_geometry(pf)
    baked = S.baked_ports(pf['body'], pf['ports'])
    if pf['ports'] and baked is None:
        raise SystemExit(f'{prefab}: baked port list not found')
    order = (sim or {}).get('order') or []
    if sim and len(order) != len(baked):
        raise SystemExit(f'{prefab}: simulator has {len(order)} ports, game {len(baked)}')
    rnodes = {tuple(round(c, 4) for c in p['pos']): p for p in pf['ports']}
    ports = {}
    for i, (pos, code, typ) in enumerate(baked):
        face = S.cells_of(geom['lo_m'], geom['size'], pos)
        d = S.FACING[code]
        cell = [face[j] + d[j] for j in range(3)]
        kind, direction = S.PORT_TYPE[typ]
        pname = order[i] if sim else 'port%d' % i
        if sim:   # the simulator's own classification must agree with the game's port type
            want = 'in' if pname in sim['inputs'] else 'out' if pname in sim['outputs'] else 'power'
            got = 'power' if kind == 'power' else direction
            if want != got:
                raise SystemExit(f'{prefab}: port {i} {pname} is {got} in the game, {want} in the simulator')
        r = rnodes.get(tuple(round(c, 4) for c in pos))
        if r is None or r['facing'] != d or (r['kind'], r['dir']) != (kind, direction):
            raise SystemExit(f'{prefab}: baked port {i} disagrees with its renderer')
        ports[pname] = {'cell': cell, 'face': list(face), 'dir': direction, 'kind': kind, 'index': i,
                        'node': r['node']}
    twin = prefab + ' M'
    twin_ok = None
    if twin in P:
        twin_ok = prefab_twin_check(pf, S.parse_prefab(P[twin]), geom)
        if not twin_ok:
            raise SystemExit(f'{twin}: ports are not the mirror of {prefab}')
    st, chain = S.blueprint_struct(pf['cls'])
    entry = {
        'name': name, 'description': L.get(prefab + '_Desc'),
        'prefab': prefab, 'hash': '%016x' % hashes.part_hash(prefab),
        'mirrored_hash': ('%016x' % hashes.part_hash(prefab, True)) if twin in P else None,
        'struct': st, 'struct_hash': '%016x' % hashes.struct_hash(st.split('+')[0]) if st else None,
        'class': pf['cls'], 'size': geom['size'], 'ports': ports,
        'settings': settings_for(st),
        'joint_faces': joint_faces(pf, geom),
    }
    info = {'chain': chain, 'twin_prefab_mirrors': twin_ok, 'size_m': pf['size_m'],
            'joints': S.joints_bbox(pf['joints'])}
    return entry, info


def validate(entries):
    """Runs the corpus checks for all entries at once. -> {key: stats}"""
    want = {}
    for key, e in entries.items():
        if e.get('prefab'):
            want[int(e['hash'], 16)] = (key, False)
            if e['mirrored_hash']:
                want[int(e['mirrored_hash'], 16)] = (key, True)
    pref = {}
    for n, v in json.load(open(os.path.join(S.BP, 'prefabs.json'), encoding='utf-8')).items():
        pref[int(v['hash'], 16)] = n
        if v.get('mirrored_hash'):
            pref[int(v['mirrored_hash'], 16)] = n + ' M'
    glass = {h for h, n in pref.items() if n.startswith('SC_Glass')}
    st = {k: {'all': collections.Counter(), 'uniq': collections.Counter(), 'rots': collections.Counter(),
              'cable_inside': 0, 'overlap_inst': 0, 'overlap_with': collections.Counter(),
              'glass_inside': 0, 'hits': collections.Counter(), 'misses': collections.Counter(),
              'miss_cells': collections.Counter(), 'kind_mismatch': collections.Counter(),
              'direct': collections.Counter(), 'port_hit': collections.Counter(), 'structs': collections.Counter(),
              'files_with_anomaly': [], 'sensor_overlap': 0, 'net_partners': collections.Counter()}
          for k in entries}
    seen, seen_net = set(), set()
    for fn, recs in S.load_corpus():
        idxs = [i for i, r in enumerate(recs) if r[0] in want]
        if not idxs:
            continue
        ctx = S.Context(recs, glass)
        occ = {}                                            # sensor footprints in this blueprint
        for i in idxs:
            h, c, k, shape, guid, sh, data = recs[i]
            key, mir = want[h]
            s = st[key]
            s['all']['M' if mir else 'N'] += 1
            s['structs'][sh] += 1
            if k not in S.ORI:
                continue
            for q in S.footprint(entries[key]['size'], c, k):
                occ.setdefault(q, set()).add(i)
            uid = (guid, c, k)
            if uid in seen:
                continue
            seen.add(uid)
            s['uniq']['M' if mir else 'N'] += 1
            s['rots'][k] += 1
            o = S.check_instance(ctx, i, entries[key], mir, c, k)
            others = [pref.get(recs[j][0], '%016x' % recs[j][0]) for j in o['origins_inside']]
            others += ['logic:' + pref.get(recs[j][0], '?') for j in o['logic_inside']]
            if o['cable_inside']:
                s['cable_inside'] += 1
            if o['cable_inside'] or others:
                s['overlap_inst'] += 1
                s['files_with_anomaly'].append((fn, c, k, mir, 'overlap', others, len(o['cable_inside'])))
            for n in others:
                s['overlap_with'][n] += 1
            if o['glass_inside']:
                s['glass_inside'] += 1
            for pname, kind, pkind, q in o['hits']:
                if kind == pkind:
                    s['hits'][(kind, mir)] += 1
                    s['port_hit'][(pname, mir)] += 1
                else:
                    s['kind_mismatch'][(pname, kind)] += 1
                    s['files_with_anomaly'].append((fn, c, k, mir, 'kind', pname, kind))
            for kind, lq, lf, q in o['misses']:
                s['misses'][kind] += 1
                s['miss_cells'][(kind, lq, lf)] += 1
                s['files_with_anomaly'].append((fn, c, k, mir, 'miss', lq, kind))
            direct_ports = {pname for pname, d2, j in o['direct']}    # a Wireless Transmitter touches twice (tx/rx)
            for pname in direct_ports:
                s['direct'][pname] += 1
                s['port_hit'][(pname, mir)] += 1
        extra = []
        for i in idxs:
            h, c, k, shape, guid, sh, data = recs[i]
            key, mir = want[h]
            if k in S.ORI:
                for pname, (pc, fc, kind, d) in S.placed_ports(entries[key], c, k, mir).items():
                    extra.append((('sensor', i, key, guid, c, k), pname, pc, fc, d, kind))
        for net in S.networks(ctx, extra):               # what each sensor port is wired to
            for owner, pname, d, kind in net:
                if owner[0] != 'sensor':
                    continue
                key = owner[2]
                uid = owner[3:] + (pname,)
                if uid in seen_net:
                    continue
                seen_net.add(uid)
                partners = [(o2[0], d2) for o2, p2, d2, k2 in net if not (o2 == owner and p2 == pname)]
                for o2, d2 in partners:
                    st[key]['net_partners'][(pname, d, d2)] += 1
        for q, ids in occ.items():                          # sensor-sensor overlaps
            if len(ids) > 1:
                for i in ids:
                    st[want[recs[i][0]][0]]['sensor_overlap'] += 1
    return st


def summarize(entry, s):
    ports = entry['ports']
    conf = [p for p in ports if s['port_hit'][(p, False)] or s['port_hit'][(p, True)]]
    hits = collections.Counter()
    for (kind, mir), n in s['hits'].items():
        hits[kind] += n
    corpus = {
        'instances': sum(s['all'].values()),
        'instances_mirrored': s['all']['M'],
        'unique_placements': sum(s['uniq'].values()),
        'ports_confirmed': '%d/%d' % (len(conf), len(ports)),
        'overlaps': s['overlap_inst'],
        'cable_hits': dict(hits),
        'cable_misses': dict(s['misses']),
        'kind_mismatches': sum(s['kind_mismatch'].values()),
        'direct_contacts': sum(s['direct'].values()),
        'twin_port_hits': sum(n for (p, m), n in s['port_hit'].items() if m),
        'port_hits': {p: s['port_hit'][(p, False)] + s['port_hit'][(p, True)] for p in ports},   # cable + direct
        'network_partners': {'%s(%s)->%s' % k: n for k, n in sorted(s['net_partners'].items())},
        'direction_conflicts': sum(n for (p, d, d2), n in s['net_partners'].items()
                                   if (d == 'out' and d2 == 'out') or (d == 'in' and d2 == 'in')),
        'orientations': dict(sorted(s['rots'].items())),
    }
    return corpus, conf


def write_json(out):
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    os.replace(tmp, OUT)


NOTES = {
    'aerometer': 'Port on the bottom face (facing -y) of a 2 x 2 x 1 plate. No corpus instance is wired, so the '
                 'port is prefab-only (baked list = renderer); the footprint is corpus-checked.',
    'inclinometer': 'Same body and port layout as the Aerometer (2 x 2 x 1, port facing -y). No corpus instance '
                    'is wired, so the port is prefab-only; the footprint is corpus-checked.',
    'distance_meter': 'Unlike most small sensors its output is on the FRONT face (z = d), at x = 1.',
    'thermoscan': 'No corpus instances (newer part). Same prefab layout as the Distance Meter (2 x 1 x 2, output '
                  'on the front face at x = 1), which is corpus-confirmed; struct from the IL2CPP inheritance chain '
                  '(EPC_SCThermoscan -> EPC_SpaceshipComponent).',
    'velocity_meter': 'Output on the back face (z = -1); the front (+z) must be unobstructed, and in Directional '
                      'mode the reading is the velocity along +z. The one overlap is an SC_FrameB with the same '
                      'origin: a wedge frame (triangular joint faces), so its 8 x 8 x 4 box has free cells.',
    'windmeter': '2 x 2 x 2; output on the back face, lower row (y = 0).',
    'blue_tank': '16 x 32 x 16 cells (2 x 4 x 2 m): the size field, not the joint areas (which span only y = 6..25). '
                 'Checked: the size-field box gives 6 port hits / 0 misses, the joint-area box 0 / 6; frames, '
                 'tanks and cables sit directly on top of the 32-cell box and line its sides at every height, '
                 'nothing inside. Fuel pipe joint on the front face at x = 8..9, y = 6..7 (not a cable port).',
    'green_tank': '8 x 24 x 8 cells (1 x 3 x 1 m), same evidence as the Blue Tank (size-field box: 6 hits / 0 '
                  'misses; joint-area box: 0 / 6; parts stacked directly on the 24-cell top).',
    'red_tank': 'No corpus instances. 16 x 16 x 16 cells from the size field (the rule the Blue and Green tanks '
                'confirm). Class EPC_SCCryotank derives from EPC_SCTank and declares no Blueprint of its own, and '
                'its InitializeEntity calls EPC_SCTank.InitializeEntity first, so it saves with the EPC_SCTank '
                'struct (the same inheritance rule is corpus-confirmed for FramePipe/FrameWithPorts -> Frame and '
                'ZoomCamera/RotationalTelescope -> Camera). Port order from the baked list: fuel (node X), '
                'cooling (node Y), power (node P).',
    'long_range_distance_meter': '2 x 2 x 4; both ports on the back face, lower row. The confirmed placements '
                                 'include orientations where local y maps to a negative world axis (13, 14, 17), so '
                                 'the min-corner rule with the full 2-cell height holds. The one overlap is an '
                                 'SC_FrameQuarterD, a corner frame (triangular joint faces) whose 4 x 4 x 4 box has '
                                 'free cells.',
    'magnetometer': '4 x 8 x 4 mast; both ports face -x (left side), bottom row. In the twin they face +x.',
    'gyro_line': 'Port order (baked list): pitch = node X (x = 1), roll = node Y (x = 2), power = node P (x = 0). '
                 'direction_conflicts = 2 is one twin placement in a scratch blueprint ("Blah") whose pitch and roll '
                 'are cabled to Data Router 2 outputs (a wiring error); the other network partners are inputs.',
    'space_gps': 'Port order (baked list): distance = node X (x = 3), longitude = X (1) (x = 2), latitude = X (2) '
                 '(x = 1), power = P (x = 0); all on the front face, bottom row.',
    'space_scanner': '4 x 4 x 8; ports on the back face, bottom row: cone (in, x = 1), distance (x = 2), power '
                     '(x = 3). The one miss and the one power-on-data contact are the same placement in an '
                     '"Autosave" snapshot (BlueprintsBin) whose cables sit two cells to -x of the ports; the other '
                     '19 placements agree.',
    'fuel_analyzer': 'Port order (baked list): value (in, x = 1, y = 0), performance = node Y (x = 1, y = 1), '
                     'stability = node X (x = 0, y = 1), power = node P (x = 0, y = 0); all on the front face. '
                     'Note performance/stability are NOT in node-name order. Also has a fuel-pipe joint on the '
                     'front face, right half (x = 2..3). Outputs not confirmed by corpus cables (only 5 unique '
                     'placements); power and input are.',
    'SC_PipeMeter': 'Not a data part: a fuel pipe segment with three indicator bars and no data or power ports '
                    '(no port children, no baked port list, no Localization port rows). Pipe joints on the -z '
                    'and +z faces. No mirrored twin prefab exists.',
    'SC_NanopipeMeter': 'Nanopipe version of the Pipe Meter: same geometry, no ports, no twin. No corpus '
                        'instances.',
    'SC_BaobaraInterferencemeter': 'Quest item (Void Watcher objective): a display that shows the distance to '
                                   'the interference source. No data or power ports. No corpus instances.',
}


def confidence(key, entry, s, conf):
    if not entry.get('prefab'):
        return 'low'
    n = sum(s['uniq'].values())
    clean = s['cable_inside'] == 0 and sum(s['misses'].values()) <= 1 and sum(s['kind_mismatch'].values()) <= 1
    if n == 0:
        return 'medium'
    if not entry['ports']:
        return 'high' if clean else 'medium'
    if clean and len(conf) == len(entry['ports']):
        return 'high'
    return 'medium'


def main():
    P = S.load_prefabs()
    T = sim_types([t for t, k in PARTS if t])
    L = localization()
    entries, infos = {}, {}
    out = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
    for type_id, key in PARTS:
        k = type_id or 'SC_' + key
        e, info = build_entry(type_id, key, P, T, L)
        entries[k], infos[k] = e, info
        out[k] = e
        write_json(out)                      # incremental: prefab-derived entry first
    stats = validate({k: e for k, e in entries.items() if e.get('prefab')})
    sch = {int(v['hash'], 16): n for n, v in json.load(open(os.path.join(S.BP, 'schemas.json'))).items()}
    for type_id, key in PARTS:
        k = type_id or 'SC_' + key
        e = entries[k]
        if e.get('prefab'):
            s = stats[k]
            seen_structs = {sch.get(h, '%016x' % h) for h in s['structs']}
            if seen_structs and seen_structs != {e['struct']}:
                raise SystemExit(f'{k}: struct {e["struct"]} but corpus uses {seen_structs}')
            e['corpus'], conf = summarize(e, s)
            e['corpus']['struct_confirmed'] = bool(seen_structs)
            e['confidence'] = confidence(k, e, s, conf)
            e['notes'] = NOTES.get(k, '')
            if s['overlap_inst']:
                e['corpus']['overlap_with'] = dict(s['overlap_with'])
            e['notes'] = e['notes'].strip()
        out[k] = e
        write_json(out)
    # report
    print('%-28s %-11s %-12s %5s %5s %6s %-7s %-22s %-14s %s' % (
        'part', 'confidence', 'size', 'inst', 'uniq', 'twins', 'ports', 'hits', 'misses', 'overlaps'))
    for type_id, key in PARTS:
        k = type_id or 'SC_' + key
        e = entries[k]
        c = e.get('corpus', {})
        print('%-28s %-11s %-12s %5s %5s %6s %-7s %-22s %-14s %s' % (
            k, e['confidence'], e['size'], c.get('instances', 0), c.get('unique_placements', 0),
            c.get('instances_mirrored', 0), c.get('ports_confirmed'), c.get('cable_hits', {}),
            c.get('cable_misses', {}), c.get('overlaps', 0)))
    for k, s in stats.items():
        for a in s['files_with_anomaly']:
            print('  anomaly', k, a)


if __name__ == '__main__':
    main()
