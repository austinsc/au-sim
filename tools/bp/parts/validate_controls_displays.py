"""Builds and validates tools/bp/parts/controls_displays.json (controls, displays, cameras, monitors).

    set PYTHONUTF8=1
    python validate_controls_displays.py            -> controls_displays.json (+ cd_validation.json evidence)

Derivation (game data, no guessing):
  * size      root EPC_SC* component, float3 at byte 12 (metres) / 0.125            (cd_geom.root_size)
  * ports     root component port table: order = game port index, facing, type        (cd_geom_ports.port_table)
              + the "Port ..." node transforms -> face cell / port cell              (cd_geom.geometry)
  * twins     "<prefab> M" GameObjects exist in globalgamemanagers.assets; their port nodes are the
              x-reflection of the normal ones (checked for every part here)
  * names     Localization.csv SC_<key>_Name / _PortN; simulator names from engine.js TYPES[t].order
  * struct    the schema struct the corpus records use; for corpus-less parts the root component's class
Validation against the corpus (cd_corpus.load(): 301 blueprints, all three cable kinds):
  (a) no cable inside the predicted footprint, no other part's footprint overlapping it
  (b) every cable cell adjacent to the part that opens toward it lands on a predicted port cell
      (hits/misses by cable kind); direct port-to-port contacts; partner ports at the other network end
  (c) mirrored twins use the reflected ports; (d) the mount face (JointsArea) touches something
The method itself is checked first on the 43 logic parts of partdb.json (must reproduce them exactly).
"""
import collections, csv, json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
BP = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(BP))
sys.path.insert(0, HERE); sys.path.insert(0, BP)
import hashes  # noqa: E402
import cd_prefab as P, cd_geom as G, cd_geom_ports as GP, cd_corpus as C, cd_analysis as A  # noqa: E402

OUT = os.path.join(HERE, 'controls_displays.json')
# parts whose real shape is smaller than their box: curved frames (Frame*/FrameHalf*/FrameQuarter* B..I) and glass
LOOSE_AABB = re.compile(r'^SC_(Frame(Half|Quarter)?[B-I]|Glass\w*)$')
EVIDENCE = os.path.join(HERE, 'cd_validation.json')
LOC = r'C:\Program Files (x86)\Steam\steamapps\common\Approximately Up\ApproximatelyUp_Data\StreamingAssets\Localization.csv'
SCHEMAS = json.load(open(os.path.join(BP, 'schemas.json'), encoding='utf-8'))
STRUCT_BY_HASH = {int(v['hash'], 16): k.split('+')[0] for k, v in SCHEMAS.items()}

# simulator type_id -> game key (prefab = "SC_" + key)
SIM_PARTS = [
    ('button', 'Button'), ('small_button', 'SmallButton'), ('switch', 'Switch'), ('small_switch', 'SmallSwitch'),
    ('stick_switch', 'StickSwitch'), ('tnt_controller', 'TNTController'), ('lever_vertical', 'LeverVertical'),
    ('lever_vertical_half', 'LeverVerticalHalf'), ('lever_horizontal', 'LeverHorizontal'), ('small_knob', 'SmallKnob'),
    ('joystick_horizontal', 'JoystickHorizontal'), ('joystick_vertical', 'JoystickVertical'),
    ('joystick_2d', 'Joystick2D'), ('joystick_3d', 'Joystick3D'),
    ('arc_90_meter', 'Arc90Meter'), ('arc_270_meter', 'Arc270Meter'), ('horizontal_meter', 'HorizontalMeter'),
    ('vertical_meter', 'VerticalMeter'), ('beeper', 'Beeper'), ('speaker', 'Speaker'),
    ('colored_light_controller', 'ColoredLightController'), ('large_datameter', 'LargeDatameter'),
    ('led_text', 'LEDText'), ('red_alert_light', 'RedAlertLight'), ('braking_point_system', 'BrakingPointSystem'),
    ('eta_system', 'ETASystem'),
    ('camera', 'Camera'), ('night_vision_camera', 'NightVisionCamera'), ('zoom_camera', 'ZoomCamera'),
    ('rotational_telescope', 'RotationalTelescope'), ('camera_overlay', 'CameraOverlay'),
    ('monitor_crt', 'MonitorCRT'), ('monitor_small_lcd', 'MonitorSmallLCD'), ('monitor_medium_lcd', 'MonitorMediumLCD'),
    ('monitor_large_lcd', 'MonitorLargeLCD'), ('monitor_small_hologram', 'MonitorSmallHologram'),
    ('monitor_medium_hologram', 'MonitorMediumHologram'), ('monitor_large_hologram', 'MonitorLargeHologram'),
]
# control/display prefabs the simulator lacks (keyed by prefab name)
EXTRA_PARTS = ['Seat', 'Whiteboard', 'ColoredLight', 'SmallToggleableLight']
# simulator source types that map onto one of the parts above
ALIASES = {'toggle': ('switch', {'value': '_buttonPressed (0/1)'}),
           'slider': ('lever_vertical', {'value': '_leverValue (with _toggle = 1 if value < 0)'})}
# parts in the same prefab family: a corpus-less member inherits the family's evidence (-> medium)
FAMILY = {'LeverHorizontal': 'LeverVertical', 'HorizontalMeter': 'VerticalMeter', 'Speaker': 'Beeper',
          'MonitorLargeLCD': 'MonitorMediumLCD', 'MonitorLargeHologram': 'MonitorMediumHologram'}

# ---- settings, per struct: field -> (default, meaning). Offsets/sizes come from schemas.json; the PDB
# (lib_burst_generated.pdb) types bools/bytes as 1 byte, so declared 4-byte flags are really 1 byte.
LABEL = ('', 'the part\'s own label text (UTF-16, max 15 chars + NUL); "" = blank')
LABEL_ROT = (0, '1 = label text rotated 180 degrees (bool, 1 byte)')
COL = (0, 'paint colour index (1 byte)')
SETTINGS = {
    'EPC_SCButton': {'_actionableLabel': LABEL,
                     '_buttonPressed': (0, 'pressed state (bool); momentary, the corpus always has 0'),
                     '_col': COL, '_labelRotated': LABEL_ROT},
    'EPC_SCSwitch': {'_actionableLabel': LABEL,
                     '_buttonPressed': (0, 'switch state (bool): 1 = on (I / up) -> output 1, 0 = off -> output 0'),
                     '_col': COL, '_labelRotated': LABEL_ROT},
    'EPC_SCLever': {'_actionableLabel': LABEL,
                    '_leverValue': (0.0, 'lever position (f32) = output. 0..1 in 0-to-1 mode; -1..1 in -1-to-1 mode, '
                                         'where the output has a +-0.025 dead zone: out = sign(v)*max(0,(|v|-0.025)/0.975) '
                                         '(SCTick_DoubleLever)'),
                    '_col': COL,
                    '_toggle': (0, 'mode button (bool): 0 = 0-to-1 mode, 1 = -1-to-1 mode (ActionableDoubleLever clamps '
                                   'to [-1,1] when set). Corpus: 243 of 375 saved levers are in mode 1, and all 11 '
                                   'negative _leverValue records are in mode 1'),
                    '_labelRotated': LABEL_ROT},
    'EPC_SCKnob': {'_actionableLabel': LABEL,
                   '_knobValue': (0.0, 'knob position = output, continuous 0..1 (prefab knob default 0, no steps)'),
                   '_col': COL, '_labelRotated': LABEL_ROT},
    'EPC_SCJoystick': {'_actionableLabel': LABEL,
                       '_leverActionableValue': ([0.0, 0.0, 0.0, 0.0], 'stick deflection, float[4] (16 B); all 0 = '
                                                                      'centred (every corpus record is 0)'),
                       '_col': COL, '_labelRotated': LABEL_ROT},
    'EPC_SCAnalogMeter': {'_actionableLabel': LABEL,
                          '_rangeMin': (0.0, 'value shown at the scale minimum (f32; Text3DMin label)'),
                          '_rangeMax': (1.0, 'value shown at the scale maximum (f32; Text3DMax label)'),
                          '_col': COL, '_labelRotated': LABEL_ROT},
    'EPC_SCBeeper': {'_knobValue': (0.5, 'volume knob (f32 0..1; prefab default 0.5, corpus 3/3 = 0.5)'),
                     '_col': COL},
    'EPC_SCSpeaker': {'_knobValue': (0.5, 'volume knob (f32 0..1; prefab default 0.5)'),
                      '_col': COL,
                      '_sound': (0, 'sound index 0..22 (Localization SpeakerSound_0.._22: Access 1..5, Alert 1..4, '
                                    'Denied 1..3, Notification 1..5, Pulse 1..6)'),
                      '_inputMode': (0, 'mode switch (bool): 0 = Play once (plays on a 0->1 edge of the input), '
                                        '1 = Repeat (re-plays while input >= 0.5); from SCTick_Speaker+ActiveJob, '
                                        'where a mode value < 0.5 selects the edge trigger')},
    'EPC_SCColoredLightController': {'_knobChannel': (0, 'channel knob index (1 byte; knob has 100 steps); must equal '
                                                         'the Colored Lights\' channel. Separate from wireless channels'),
                                     '_col': COL},
    'EPC_SCDataMeter': {'_actionableLabel': LABEL, '_col': COL,
                        '_inputSwitch': (0, 'display switch (bool): passed as `asFloat` to CRPText3DString.FromFloatTo8Digit '
                                            '(1 = show decimals, 0 = whole number); corpus mostly 0'),
                        '_labelRotated': LABEL_ROT},
    'EPC_SCLEDText': {'_actionableLabel': ('', 'the text that lights up (UTF-16, max 15 chars)'), '_col': COL,
                      '_knobColor': (0, 'colour knob index 0..10 (11 steps; probably the ColoredLight_Col_0..10 list: '
                                        'White, Yellow, Orange, Purple, Pink, Red, Teal, Green, Blue, Brown, Cyan)'),
                      '_labelRotated': LABEL_ROT},
    'EPC_SpaceshipComponent': {'_col': COL},
    'EPC_SCCamera': {'_cameraOrientation': (0, 'Orientation Knob index 0..3 (4 steps): image rotation in 90-degree '
                                                'steps'),
                     '_col': COL},
    'EPC_SCCameraOverlay': {
        '_cameraOrientation': (0, 'Knob Rotation index 0..3 (4 steps): overlay rotation in 90-degree steps'),
        '_col': COL,
        '_alignment': (0, 'Knob Alignment index 0..2 (3 steps): text alignment'),
        '_size': (2, 'Knob Size index 0..4 (5 steps; prefab knob default 0.5 = index 2, corpus majority 2)'),
        '_graphics': (0, 'Knob Graphics index 0..1 (2 steps); corpus majority 1'),
        '_position': (0, 'Knob Position index 0..8 (9 steps): where the text block sits on screen'),
        '_inputSwitches': (15, 'bit k = Input Switch k (row k+1) on; corpus 0x0f in 48/89, 0x00 in 30/89'),
        '_label0': ('', 'row 1 caption (UTF-16, max 15 chars)'), '_label1': ('', 'row 2 caption'),
        '_label2': ('', 'row 3 caption'), '_label3': ('', 'row 4 caption')},
    'EPC_SCMonitor': {'_toggle': (1, 'power switch (bool): 1 = on (corpus: 1 in almost every record)'),
                      '_col': COL,
                      '_mode': (0, 'Knob Mode index 0..8 (9 steps), Localization Monitor_Mode_*: 0 Primary only, '
                                   '1 Secondary only, 2 Primary + Secondary overlay, 3 Split vertical, 4 Split '
                                   'horizontal, 5..8 Primary + small Secondary bottom-left, bottom-right, top-left, '
                                   'top-right (order of the strings; LCD/hologram only, CRT has one input)')},
    'EPC_SCSeat': {'_leverActionableValue': (0.0, 'seat lever position (f32); corpus 0 (304) or 1 (41)'), '_col': COL},
    'EPC_SCWhiteboard': {'_extraData': (0, 'int32 handle of the drawing data (0 = blank)'), '_col': COL},
    'EPC_SCColoredLight': {'_knobIntensity': (0.7, 'intensity knob (f32 0..1; prefab default 0.7)'),
                           '_knobColor': (0, 'colour knob 0..10 = ColoredLight_Col_0..10 (White, Yellow, Orange, '
                                             'Purple, Pink, Red, Teal, Green, Blue, Brown, Cyan)'),
                           '_knobChannel': (0, 'channel knob index (101 steps; 0 presumably = Manual Mode, else '
                                               'follows the Colored Light Controller on that channel)'),
                           '_col': COL},
    'EPC_SCActionableLight': {'_toggle': (1, 'light switch (bool): 1 = on (corpus 208/277)'), '_col': COL},
}
PART_NOTES = {
    'SC_SmallToggleableLight': 'no data port: it is switched by hand only (EPC_SCActionableLight _toggle)',
    'SC_ColoredLight': 'no data port: driven wirelessly by a Colored Light Controller on the same channel',
    'SC_Seat': 'no ports; two dangling power-cable stubs end on a seat face in one blueprint (not ports)',
    'SC_RotationalTelescope': 'uses EPC_SCCamera; _cameraOrientation is always 0 (no orientation knob)',
    'SC_MonitorCRT': 'one video input only (Port A); the power port sits beside it on the same face',
    'SC_LEDText': '_actionableLabel is the text that lights up',
}
EXTRA_FIELD_NOTES = {
    'EPC_SCBeeper': '_pitch (byte @25, pitch knob 0..10, 5 = default) exists in the current game build (PDB) but '
                    'is not in schemas.json (older saves); omit it and the game keeps its default.',
}


def loc():
    rows = list(csv.reader(open(LOC, encoding='utf-8')))
    return {r[0]: r[1] for r in rows[1:] if r}


def engine_types():
    script = ("const {TYPES}=require('./engine.js');const o={};for(const[t,d] of Object.entries(TYPES))"
              "o[t]={game:d.game,order:d.order||null,inputs:d.inputs,outputs:d.outputs,power:d.power||[],"
              "kinds:d.kinds||{}};process.stdout.write(JSON.stringify(o));")
    return json.loads(subprocess.check_output(['node', '-e', script], cwd=ROOT))


def write_json(obj):
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    os.replace(tmp, OUT)


# ------------------------------------------------------------------------------------------------
def check_method_on_logic_parts():
    """The derivation must reproduce partdb.json (43 logic parts) exactly: size, port cells, port order."""
    db = json.load(open(os.path.join(BP, 'partdb.json'), encoding='utf-8'))
    bad = []
    for t, v in db.items():
        g = G.geometry(v['prefab'])
        _, table = GP.port_table(v['prefab'])
        cells = [tuple(g['ports'][n]['cell']) for n, f, ty in table]
        want = [tuple(p['cell']) for p in v['ports'].values()]
        if t == 'wireless_transmitter':
            want = want[:1]
        if g['size'] != v['size'] or cells != want:
            bad.append((t, g['size'], v['size'], cells, want))
    return len(db), bad


def mount_faces(prefab, size):
    """Canonical outward normals of the faces carrying JointsArea polygons (the faces it is built onto)."""
    half = [s * 0.0625 for s in size]
    out = set()
    for name, a0, a1, pts in P.polys(prefab):
        for ax in range(3):
            vals = {round(p[ax], 4) for p in pts}
            if len(vals) == 1:
                v = vals.pop()
                if abs(abs(v) - half[ax]) < 1e-3:
                    n = [0, 0, 0]; n[ax] = 1 if v > 0 else -1
                    out.add(tuple(n))
    return sorted(out)


def build_static(t, key, types, L, twins_present):
    """Entry from game data only (no corpus)."""
    pf = 'SC_' + key
    e = {'name': L.get(pf + '_Name', key), 'prefab': pf, 'hash': f'{hashes.part_hash(pf):016x}',
         'mirrored_hash': f'{hashes.part_hash(pf, True):016x}' if (pf + ' M') in twins_present else None}
    if pf not in P.dump():
        e.update({'placeable': False, 'struct': None, 'size': None, 'ports': {}, 'settings': {},
                  'corpus': {'instances': 0, 'ports_confirmed': '0/0', 'overlaps': 0}, 'confidence': 'low',
                  'mirrored_hash': None})
        return e, None
    g = G.geometry(pf)
    off, table = GP.port_table(pf)
    tw_geom = G.geometry(pf + ' M') if (pf + ' M') in P.dump() else None
    if tw_geom is not None:
        rf = G.reflect(g)
        assert {n: p['cell'] for n, p in tw_geom['ports'].items()} == {n: p['cell'] for n, p in rf['ports'].items()}, pf
        assert tw_geom['size'] == g['size'], pf
    e['placeable'] = True
    e['size'] = g['size']
    e['root_class'] = g['root']
    ports = {}
    if t and types.get(t):
        ty = types[t]
        order = ty['order'] or (ty['inputs'] + ty['outputs'] + ty['power'])
        if len(order) != len(table):
            raise SystemExit(f'{t}: simulator has {len(order)} ports, game {len(table)}')
        for i, (sim, (node, fcode, gtype)) in enumerate(zip(order, table)):
            p = g['ports'][node]
            kind = ty['kinds'].get(sim, 'data')
            if gtype == 2:
                kind = 'power'
            want_dir = 'in' if sim in ty['inputs'] else 'out' if sim in ty['outputs'] else 'in'
            game_dir = {0: 'in', 1: 'out', 2: 'in', 3: 'both'}[gtype]
            if want_dir != game_dir:
                raise SystemExit(f'{t}.{sim}: simulator dir {want_dir} vs game type {GP.TYPE[gtype]}')
            if (sim in ty['power']) != (gtype == 2):
                raise SystemExit(f'{t}.{sim}: power mismatch')
            ports[sim] = {'cell': list(p['cell']), 'face': list(p['face']), 'facing': list(p['facing']),
                          'dir': want_dir, 'kind': kind,
                          'cable': 'SC_PowerCable' if gtype == 2 else 'SC_DataCable',
                          'game_index': i, 'game_type': GP.TYPE[gtype], 'node': node,
                          'game_text': L.get(f'{pf}_Port{i}', '').replace('<u>', '').replace('</u>', '')}
    elif table:
        raise SystemExit(f'{pf}: has ports but no simulator type')
    e['ports'] = ports
    e['mount_faces'] = [list(n) for n in mount_faces(pf, g['size'])]
    return e, {'geom': g, 'table': table, 'table_offset': off}


def settings_for(struct):
    out = {}
    fields = {f: (o, s) for f, o, s in SCHEMAS[struct + '+Blueprint+BlueprintData']['fields']}
    for f, (default, meaning) in SETTINGS[struct].items():
        o, s = fields[f]
        out[f] = {'default': default, 'meaning': meaning, 'offset': o,
                  'bytes': 1 if (s == 4 and (f in ('_labelRotated', '_toggle', '_buttonPressed', '_inputSwitch',
                                                    '_inputMode'))) else s}
    return out


# ------------------------------------------------------------------------------------------------
def corpus_stats(bps, mine):
    """Per (prefab, mirrored): evidence counters from every corpus instance."""
    S = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    examples = collections.defaultdict(list)
    for bi, bp in enumerate(bps):
        if not any(r.part in mine for r in bp):
            continue
        B = A.Blueprint(bp)
        netcache = {}
        for i, p in B.parts.items():
            r = bp[i]
            if r.part not in mine:
                continue
            key = (p['prefab'], p['mirrored'])
            s = S[key]
            s['n']['instances'] += 1
            s['ori'][r.rot] += 1
            s['struct'][STRUCT_BY_HASH.get(r.struct, f'?{r.struct:016x}')] += 1
            foot = B.footprint(i)
            fset = set(foot)
            inside = sum(1 for c in foot if c in B.cables)
            s['n']['cables_inside'] += inside
            s['n']['inst_cables_inside'] += bool(inside)
            ov = B.overlapping(i)
            strict = [j for j in ov if not LOOSE_AABB.match(B.parts[j]['prefab'])]
            loose = [j for j in ov if LOOSE_AABB.match(B.parts[j]['prefab'])]
            if strict:
                s['n']['inst_overlap'] += 1
                for j in strict:
                    s['overlap_with'][B.parts[j]['prefab']] += 1
            if loose:
                s['n']['inst_overlap_loose'] += 1
                for j in loose:
                    s['overlap_loose_with'][B.parts[j]['prefab']] += 1
            if ov and len(examples[key]) < 3:
                examples[key].append({'file': r.src, 'cell': r.cell, 'rot': r.rot,
                                      'overlaps': sorted({B.parts[j]['prefab'] for j in ov})})
            # (b) adjacent cables that open toward the part
            pmap = {pc: (n, inward) for n, (pc, fc, inward) in p['ports'].items()}
            for c in foot:
                for d in A.DIRS:
                    nb = (c[0] + d[0], c[1] + d[1], c[2] + d[2])
                    if nb in fset or nb not in B.cables:
                        continue
                    kind, opens = B.cables[nb]
                    back = (-d[0], -d[1], -d[2])
                    if back in opens:
                        if nb in pmap and pmap[nb][1] == back:
                            s['adj_hit'][kind] += 1
                        else:
                            s['adj_miss'][kind] += 1
            # ports
            for n, (pc, fc, inward) in p['ports'].items():
                gtype = p['types'].get(n)
                cab = B.cables.get(pc)
                if cab:
                    kind, opens = cab
                    if inward in opens:
                        s['port_hit'][(n, kind)] += 1
                        if pc not in netcache:
                            cells = B.network(pc)
                            eps = B.endpoints(cells)
                            for c2 in cells:
                                netcache[c2] = eps
                        for (j, n2, k2) in netcache[pc]:
                            if j == i and n2 == n:
                                continue
                            q = B.parts[j]
                            s['partner'][(n, q['prefab'] + (' M' if q['mirrored'] else ''), n2)] += 1
                            s['partner_type'][(n, GP.TYPE.get(q['types'].get(n2), '?'))] += 1
                    else:
                        s['port_cable_passing'][(n, kind)] += 1
                for (j, n2, fc2, inw2) in B.port_at.get(fc, ()):
                    if j != i and fc2 == pc:
                        q = B.parts[j]
                        s['contact'][(n, q['prefab'] + (' M' if q['mirrored'] else ''), n2)] += 1
                        s['partner_type'][(n, GP.TYPE.get(q['types'].get(n2), '?'))] += 1
                        s['port_contact'][n] += 1
            # (d) mount faces touching another part or a cable
            mf = mount_faces(p['prefab'], p['geom']['size'])
            if mf:
                m = G.ORI[r.rot]
                touched = False
                w, h, d_ = p['geom']['size']
                for nrm in mf:
                    wn = G.rot(m, nrm)
                    for c in foot:
                        nb = (c[0] + wn[0], c[1] + wn[1], c[2] + wn[2])
                        if nb in fset:
                            continue
                        if nb in B.cables or B.parts_at(nb, exclude=i):
                            touched = True
                            break
                    if touched:
                        break
                s['n']['mount_checked'] += 1
                s['n']['mount_touch'] += touched
    return S, examples


def summarize(e, S, examples, prefab, sim_ports):
    keys = [(prefab, False), (prefab, True)]
    tot = collections.Counter()
    hit = collections.defaultdict(collections.Counter)
    contact = collections.Counter()
    adj_hit, adj_miss = collections.Counter(), collections.Counter()
    overlap_with = collections.Counter()
    overlap_loose = collections.Counter()
    partner_type = collections.defaultdict(collections.Counter)
    partners = collections.Counter()
    structs = collections.Counter()
    passing = collections.Counter()
    for k in keys:
        s = S.get(k)
        if not s:
            continue
        tot.update(s['n'])
        structs.update(s['struct'])
        adj_hit.update(s['adj_hit']); adj_miss.update(s['adj_miss'])
        overlap_with.update(s['overlap_with'])
        overlap_loose.update(s['overlap_loose_with'])
        for (n, kind), v in s['port_hit'].items():
            hit[n][kind] += v
        for (n, kind), v in s['port_cable_passing'].items():
            passing[(n, kind)] += v
        for n, v in s['port_contact'].items():
            contact[n] += v
        for (n, t), v in s['partner_type'].items():
            partner_type[n][t] += v
        for (n, pf2, n2), v in list(s['partner'].items()) + list(s['contact'].items()):
            partners[(n, pf2, n2)] += v
    node_to_sim = {p['node']: sim for sim, p in sim_ports.items()}
    confirmed = 0
    port_ev = {}
    bad_dir = 0
    for sim, p in sim_ports.items():
        n = p['node']
        want = 'power' if p['game_type'] == 'power' else 'data'
        good_hits = hit[n].get(want, 0)
        wrong = sum(v for kd, v in hit[n].items() if kd != want)
        pt = partner_type[n]
        # a data output must never meet another output (nor an input another input); a port meeting a port of
        # the other cable family (data vs power) is not a connection at all, only reported
        if p['game_type'] == 'data_out':
            clash, incompatible = pt.get('data_out', 0), pt.get('power', 0)
        elif p['game_type'] == 'data_in':
            clash, incompatible = pt.get('data_in', 0), pt.get('power', 0)
        else:
            clash, incompatible = 0, pt.get('data_in', 0) + pt.get('data_out', 0) + pt.get('data_both', 0)
        bad_dir += clash
        ok = (good_hits + contact[n]) > 0
        confirmed += ok
        port_ev[sim] = {'node': n, 'cable_hits': dict(hit[n]), 'direct_contacts': contact[n],
                        'cable_passing_not_open': sum(v for (nn, kd), v in passing.items() if nn == n),
                        'wrong_kind_hits': wrong, 'partner_types': dict(pt), 'direction_clashes': clash,
                        'incompatible_partners': incompatible,
                        'top_partners': [f'{pf2}:{n2} x{v}' for (nn, pf2, n2), v in partners.most_common() if nn == n][:6]}
    inst = tot['instances']

    def variant_confirmed(k):
        """ports confirmed by the normal (k = False) or mirrored (k = True) instances alone."""
        s = S.get((prefab, k))
        if not s:
            return None
        ok = 0
        for sim, p in sim_ports.items():
            want = 'power' if p['game_type'] == 'power' else 'data'
            ok += (s['port_hit'].get((p['node'], want), 0) + s['port_contact'].get(p['node'], 0)) > 0
        return f'{ok}/{len(sim_ports)}'

    corpus = {'instances': inst,
              'instances_normal': S.get(keys[0], {}).get('n', {}).get('instances', 0) if keys[0] in S else 0,
              'instances_mirrored': S.get(keys[1], {}).get('n', {}).get('instances', 0) if keys[1] in S else 0,
              'ports_confirmed': f'{confirmed}/{len(sim_ports)}',
              'ports_confirmed_normal': variant_confirmed(False),
              'ports_confirmed_mirrored': variant_confirmed(True),
              'overlaps': tot['inst_overlap'],
              'overlaps_with_curved_frame_or_glass_box': tot['inst_overlap_loose'],
              'cables_inside': tot['cables_inside'],
              'adjacent_cables_opening_toward_part': {'on_port': dict(adj_hit), 'elsewhere': dict(adj_miss)},
              'mount_face_touching': f"{tot['mount_touch']}/{tot['mount_checked']}",
              'struct_seen': dict(structs)}
    if overlap_with:
        corpus['overlap_with'] = dict(overlap_with.most_common(6))
    if overlap_loose:
        corpus['loose_overlap_with'] = dict(overlap_loose.most_common(6))
    return corpus, port_ev, confirmed, bad_dir


def main():
    t0 = time.time()
    n_logic, bad = check_method_on_logic_parts()
    print(f'method check on partdb logic parts: {n_logic - len(bad)}/{n_logic} reproduced exactly', bad[:3])
    if bad:
        raise SystemExit('derivation does not reproduce partdb.json')
    L = loc()
    types = engine_types()
    twins_present = P.all_sc_gameobjects()
    result, evidence = {}, {'method_check': f'{n_logic - len(bad)}/{n_logic} partdb logic parts reproduced'}

    plan = [(t, k) for t, k in SIM_PARTS] + [(None, k) for k in EXTRA_PARTS]
    statics = {}
    for t, key in plan:
        e, extra = build_static(t, key, types, L, twins_present)
        statics[(t, key)] = (e, extra)

    mine = {}
    for (t, key), (e, extra) in statics.items():
        if e.get('placeable'):
            mine[hashes.part_hash(e['prefab'])] = e['prefab']
            mine[hashes.part_hash(e['prefab'], True)] = e['prefab']
    bps = C.load()
    S, examples = corpus_stats(bps, mine)
    print(f'corpus pass done in {time.time() - t0:.0f}s')

    # pass 1: corpus-backed parts; pass 2: corpus-less parts (their confidence leans on their family)
    fam_conf, pending = {}, {}
    order_keys = ['name', 'prefab', 'hash', 'mirrored_hash', 'struct', 'struct_hash', 'size', 'ports',
                  'mirrored_ports', 'settings', 'corpus', 'confidence', 'notes', 'placeable', 'root_class',
                  'mount_faces']
    for t, key in plan:
        e, extra = statics[(t, key)]
        out_key = t if t else e['prefab']
        result[out_key] = None                      # keep the planned key order
        if not e.get('placeable'):
            e['notes'] = (f'No "{e["prefab"]}" prefab exists in the game assets (globalgamemanagers.assets lists '
                          '571 SC_* GameObjects incl. twins; none for this key), so the part cannot be placed; '
                          'substitute it. ')
            if key == 'ETASystem':
                e['notes'] += ('Code and the settings struct EPC_SCETASystem (_knobValue) exist, and Localization '
                               'has SC_ETASystem_Port0..3, but the part is not shipped.')
            if key == 'TNTController':
                e['notes'] += 'Localization marks it as a demo-only part ("Thanks for playing the Demo!").'
            pending[out_key] = ('final', e, None, None)
            continue
        corpus, port_ev, confirmed, clashes = summarize(e, S, examples, e['prefab'], e['ports'])
        structs = corpus.pop('struct_seen')
        if structs:
            struct = max(structs, key=structs.get)
            if len(structs) > 1:
                raise SystemExit(f'{e["prefab"]}: several structs {structs}')
        else:
            struct = e['root_class']
            if struct + '+Blueprint+BlueprintData' not in SCHEMAS:
                raise SystemExit(f'{e["prefab"]}: no corpus record and {struct} has no schema entry')
        e['struct'] = struct + '+Blueprint+BlueprintData'
        e['struct_hash'] = SCHEMAS[e['struct']]['hash']
        e['settings'] = settings_for(struct)
        e['corpus'] = corpus
        if e['mirrored_hash'] is not None:
            tg = G.geometry(e['prefab'] + ' M')
            e['mirrored_ports'] = {sim: {'cell': list(tg['ports'][p['node']]['cell']),
                                         'face': list(tg['ports'][p['node']]['face']),
                                         'facing': list(tg['ports'][p['node']]['facing'])}
                                   for sim, p in e['ports'].items()}
        n = corpus['instances']
        nports = len(e['ports'])
        miss = sum(corpus['adjacent_cables_opening_toward_part']['elsewhere'].values())
        if n == 0:
            pending[out_key] = ('family', e, port_ev, (key, struct, clashes))
            continue
        clean = corpus['cables_inside'] == 0 and corpus['overlaps'] == 0 and clashes == 0
        if clean and miss == 0 and confirmed == nports:
            conf = 'high'
            why = (f'corpus confirms the footprint and {confirmed}/{nports} ports' if nports else
                   'corpus confirms the footprint (no ports)')
            if n < 3:
                why += f' (only {n} instance{"s" if n > 1 else ""}; derivation identical to the validated parts)'
        elif clean and confirmed == nports and miss <= 2:
            conf = 'high'
            why = ((f'corpus confirms the footprint and {confirmed}/{nports} ports' if nports else
                    'corpus confirms the footprint (no ports)') + f'; {miss} dangling cable end(s) touch it')
        else:
            conf = 'medium'
            why = (f'corpus: {confirmed}/{nports} ports confirmed, {miss} cable ends elsewhere, {clashes} direction '
                   f'clashes, {corpus["cables_inside"]} cables inside, {corpus["overlaps"]} overlaps')
        fam_conf[key] = conf
        pending[out_key] = ('final', e, port_ev, (why, struct, clashes))

    for out_key, (state, e, port_ev, info) in pending.items():
        if e.get('placeable'):
            if state == 'family':
                key, struct, clashes = info
                fam = FAMILY.get(key)
                conf = 'medium' if fam else 'low'
                why = ('no corpus instances: prefab-derived only (the same derivation reproduces all 43 partdb '
                       'logic parts and every corpus-checked part here)'
                       + (f'; same family as {fam} ({fam_conf.get(fam)} confidence)' if fam else ''))
            else:
                why, struct, clashes = info
                conf = fam_conf[[k for t, k in plan if (t or 'SC_' + k) == out_key][0]]
            e['confidence'] = conf
            corpus = e['corpus']
            notes = [why]
            if e['mirrored_hash'] is None:
                notes.append('no mirrored twin prefab exists in the game assets (cannot be mirrored)')
            elif e['ports']:
                notes.append('twin "<prefab> M": ports reflected along local x (dx -> w-1-dx, x facing negated); '
                             'mirrored_ports is read from the twin prefab itself')
            else:
                notes.append('a twin "<prefab> M" prefab exists (no ports to reflect)')
            if any(p['kind'] == 'video' for p in e['ports'].values()):
                notes.append('video ports are ordinary data ports in the game (types data_in/data_out) and are '
                             'wired with SC_DataCable; corpus video links run camera/overlay X -> monitor A/B, also '
                             'through Data Redirector 3, Data Router 2, Wireless Transmitter and port frames')
            if struct in EXTRA_FIELD_NOTES:
                notes.append(EXTRA_FIELD_NOTES[struct])
            if PART_NOTES.get(e['prefab']):
                notes.append(PART_NOTES[e['prefab']])
            if corpus.get('loose_overlap_with'):
                notes.append('box overlaps only with curved frames/glass, whose boxes are larger than their shape: '
                             + ', '.join(corpus['loose_overlap_with']))
            e['notes'] = '; '.join(notes)
            if port_ev is not None:
                evidence[out_key] = {'ports': port_ev, 'orientations': {
                    ('mirrored' if mir else 'normal'): dict(S[(e['prefab'], mir)]['ori'].most_common())
                    for mir in (False, True) if (e['prefab'], mir) in S},
                    'overlap_examples': examples.get((e['prefab'], False), [])
                    + examples.get((e['prefab'], True), [])}
            result[out_key] = {k: e[k] for k in order_keys if k in e}
            print(f'{out_key:26s} {conf:6s} n={corpus["instances"]:4d} ports {corpus["ports_confirmed"]:>5s} '
                  f'inside={corpus["cables_inside"]} overlaps={corpus["overlaps"]}'
                  f'+{corpus["overlaps_with_curved_frame_or_glass_box"]}loose '
                  f'adj={corpus["adjacent_cables_opening_toward_part"]} mount={corpus["mount_face_touching"]} '
                  f'clashes={clashes}')
        else:
            result[out_key] = e
            print(f'{out_key:26s} not placeable')
        write_json({k: v for k, v in result.items() if v is not None})
    for alias, (target, params) in ALIASES.items():
        a = dict(result[target])
        a['alias_of'] = target
        a['params_to_settings'] = params
        a['notes'] = f'simulator source type "{alias}" is placed as {result[target]["prefab"]}; ' + a['notes']
        result[alias] = a
    write_json(result)
    json.dump(evidence, open(EVIDENCE, 'w', encoding='utf-8'), indent=1, ensure_ascii=False, default=str)
    print(f'wrote {OUT} ({len(result)} entries) and {EVIDENCE} in {time.time() - t0:.0f}s')


def check_json():
    """End-to-end test of the written JSON alone (no cd_geom objects): place every corpus instance with the
    JSON's size/ports (twins with mirrored_ports), the orientation table and min-corner anchoring, and count
    cables that open toward each predicted port cell, plus cables found inside the predicted footprints."""
    data = json.load(open(OUT, encoding='utf-8'))
    by_hash = {}
    for k, v in data.items():
        if v.get('placeable') and 'alias_of' not in v:
            by_hash[int(v['hash'], 16)] = (k, v, False)
            if v.get('mirrored_hash'):
                by_hash[int(v['mirrored_hash'], 16)] = (k, v, True)
    hits, open_elsewhere, inside = collections.Counter(), collections.Counter(), 0
    for bp in C.load():
        rel = [r for r in bp if r.part in by_hash]
        if not rel:
            continue
        cables = {}
        for r in bp:
            cs = C.cable_shape(r)
            if cs:
                m = G.ORI[r.rot]
                cables[r.cell] = {G.rot(m, o) for o in A.OPEN.get(cs[1], ())}
        for r in rel:
            k, v, mir = by_hash[r.part]
            w, h, d = v['size']
            m = G.ORI[r.rot]
            corners = [G.rot(m, (x, y, z)) for x in (0, w - 1) for y in (0, h - 1) for z in (0, d - 1)]
            mn = tuple(min(c[i] for c in corners) for i in range(3))
            place = lambda q: tuple(r.cell[i] + G.rot(m, q)[i] - mn[i] for i in range(3))
            foot = {place((x, y, z)) for x in range(w) for y in range(h) for z in range(d)}
            inside += sum(1 for c in foot if c in cables)
            ports = v['mirrored_ports'] if mir else v['ports']
            for name, p in ports.items():
                pc = place(tuple(p['cell']))
                inward = G.rot(m, tuple(-c for c in p['facing']))
                if pc in cables and inward in cables[pc]:
                    hits[k] += 1
            pcs = {place(tuple(p['cell'])) for p in ports.values()}
            for c in foot:
                for dd in A.DIRS:
                    nb = (c[0] + dd[0], c[1] + dd[1], c[2] + dd[2])
                    if nb not in foot and nb in cables and (-dd[0], -dd[1], -dd[2]) in cables[nb] and nb not in pcs:
                        open_elsewhere[k] += 1
    return sum(hits.values()), dict(open_elsewhere), inside


if __name__ == '__main__':
    main()
    h, oe, ins = check_json()
    print(f'JSON end-to-end check: {h} cable hits on predicted port cells, {ins} cables inside footprints, '
          f'cable ends opening toward a part elsewhere: {oe or 0}')
