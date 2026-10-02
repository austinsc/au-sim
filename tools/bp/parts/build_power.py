"""Builds power.json from the prefab-derived geometry (power_geom.py) and the corpus statistics
(power_validation.json from validate_power.py, power_cables_stats.json from power_cables.py).

    python build_power.py

The file is written atomically after every entry, so it is valid JSON at all times.
"""
import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
BP = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(BP))
sys.path.insert(0, HERE)
sys.path.insert(0, BP)
import power_geom as G
import hashes
from validate_power import TARGETS
from power_cable_rules import cable_rules

OUT = os.path.join(HERE, 'power.json')
SCHEMA_CLASSES = {k.split('+')[0] for k in json.load(open(os.path.join(BP, 'schemas.json'), encoding='utf-8'))}
# blueprint struct of classes whose own class has none (checked on 208 corpus prefabs: a part uses its
# class's Blueprint struct, else the nearest base class's; EPC_SpaceshipComponent is the root)
BASE_STRUCT = {'EPC_SCBattery': 'EPC_SpaceshipComponent', 'EPC_SCPipe': 'EPC_SpaceshipComponent',
               'EPC_SCPipeElectricValve': 'EPC_SpaceshipComponent', 'EPC_SCPipeMeter': 'EPC_SpaceshipComponent'}


def sim_types():
    js = ("const {TYPES}=require('./engine.js');const o={};for(const [k,v] of Object.entries(TYPES))"
          "o[k]={order:v.order,inputs:v.inputs,outputs:v.outputs,power:v.power,kinds:v.kinds,game:v.game};"
          "console.log(JSON.stringify(o))")
    try:
        return json.loads(subprocess.run(['node', '-e', js], cwd=ROOT, capture_output=True, text=True).stdout)
    except Exception as e:
        print('warning: engine.js not read:', e)
        return {}


SIM = sim_types()

CONF = {  # key -> (confidence, notes)
    'small_disposable_battery': ('high', '4x4x4 block. One power port on the back face (z = -1), x = 2, y = 1.'),
    'medium_disposable_battery': ('high', '4x8x8 (w x h x d). Both ports on the back face at y = 3: power x = 3, '
                                  'level (data output) x = 2. The level output is seldom wired; its port cell often '
                                  'holds the power cable leaving the power port sideways (corpus "cable_not_open").'),
    'large_disposable_battery': ('high', '8x16x8. Both ports on the back face, bottom row (y = 0): power x = 7, level '
                                 '(data output) x = 6.'),
    'small_rechargeable_battery': ('high', '4x4x4. One power port on the back face at x = 3, y = 0.'),
    'medium_rechargeable_battery': ('high', '4x8x8. Back face, bottom row: power x = 3, level (data output) x = 2. '
                                    'Batteries stacked back to back touch power-to-power directly (49 + 49 contacts).'),
    'large_rechargeable_battery': ('medium', 'No corpus instance (prefab only, twin prefab dumped). Same 8x16x8 size '
                                   'and the same port layout as the Large Disposable Battery, which is confirmed on 440 '
                                   'instances.'),
    'solar_panel': ('high', '8x1x16 flat panel. Two power ports, both at x = 0: a on the back face, b on the front '
                    'face (16 cells apart). Both are the same circuit.'),
    'autohemisphere_solar_panel': ('high', '8x8x8. One power port on the front face, bottom row, x = 4.'),
    'dynamo_box': ('high', '4x4x4. One power port on the LEFT face (-x) at the bottom back corner, cell (-1,0,0); '
                   'the twin has it on the right face, (4,0,0). Only 5 corpus instances, all wired there.'),
    'power_router': ('high', '2x1x2. Four power ports, two on the back face and two on the front; one circuit, so '
                     'they are interchangeable. Names follow the game port order (Port0..3), which runs front x=1, '
                     'front x=0, back x=0, back x=1. No mirrored twin.'),
    'large_power_router': ('high', '4x1x2. Eight power ports, four on the back face and four on the front; one '
                           'circuit. Game port order: front x = 3..0, then back x = 0..3. No mirrored twin.'),
    'fuse_box': ('high', '4x4x1 upright plate. Both power ports on the TOP face (+y): a at x = 2, b at x = 1.'),
    'power_blocker': ('high', '2x1x2. Back face: block (data input) x = 1 and a (power) x = 0; front face: b (power) '
                      'x = 0. Power flows a <-> b unless block >= 0.5.'),
    'power_generation_meter': ('high', '2x1x2. Both ports on the front face: generation (data output) x = 1, power '
                               'x = 0.'),
    'power_usage_meter': ('high', '2x1x2. Both ports on the front face: usage (data output) x = 1, power x = 0.'),
    'pipe_electric_valve': ('medium', '2x2x2 pipe segment along z (pipe ends -z and +z), electric ports on the top '
                            'face: open (data input) x = 0, power x = 1. 2 corpus instances, both ports wired and both '
                            'ends joined. One-way valve: in both corpus designs (Gecko, Outcast) the -z end leads only '
                            'to tanks and the +z end only to thrusters, so inlet = end_-z, outlet = end_+z '
                            '(2/2, not confirmed in code).'),
    'nanopipe_electric_valve': ('medium', 'No corpus instance (prefab only, twin dumped). Same geometry and ports as '
                                'the Pipe With Electric Valve.'),
    'SC_PipeFull': ('high', '2x2x8 straight pipe along z; pipe ends are the whole 2x2 faces at -z and +z.'),
    'SC_PipeHalf': ('high', '2x2x4 straight pipe; ends at -z and +z.'),
    'SC_PipeQuarter': ('high', '2x2x2 straight pipe; ends at -z and +z.'),
    'SC_PipeCorner': ('high', '2x2x2 elbow; ends at +z and +x (twin: +z and -x).'),
    'SC_PipeThreeway': ('high', '2x2x2 tee; ends at -z, +z and +x (twin: -x).'),
    'SC_PipeCross': ('medium', '2x2x2 cross; ends at -z, +z, -x and +x. 2 corpus instances, all ends joined.'),
    'SC_PipeManualValve': ('high', '2x2x2 one-way valve; ends at -z and +z. Geometry high; flow direction '
                           'unresolved: the only corpus design (two valves in a loop) is inconclusive; by analogy with '
                           'the electric valve, inlet probably end_-z, outlet end_+z.'),
    'SC_PipeMeter': ('high', '2x2x2 inline meter; ends at -z and +z. No electric ports (display only).'),
    'SC_PipeDecoupling': ('medium', 'No corpus instance. 2x2x2; plain end at -z, decoupling end at +z '
                          '(SpaceshipComponentAreaPoly _type 2, "the marked side").'),
}
for _n in ('Full', 'Half', 'Quarter', 'Corner', 'Threeway', 'Cross', 'ManualValve', 'Meter', 'Decoupling'):
    CONF['SC_Nanopipe' + _n] = ('medium', 'No corpus instance (prefab only). Same size and pipe ends as SC_Pipe'
                                + _n + '.')


def atomic_dump(obj, path):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.tmp')
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, indent=1)
    os.replace(tmp, path)


def struct_of(cls):
    if cls in SCHEMA_CLASSES:
        return cls
    return BASE_STRUCT.get(cls, 'EPC_SpaceshipComponent')


def sim_port_names(key, ports, child_map):
    """engine.js lists a type's ports in the game's port order (= Localization SC_<X>_PortN)."""
    sim = SIM.get(key)
    if sim and len(sim['order']) == len(ports):
        return {i: sim['order'][i] for (nm, k, d, f, c, fa, i, t) in ports}
    return {i: child_map.get(nm, nm) for (nm, k, d, f, c, fa, i, t) in ports}


def end_name(nrm):
    return 'end_' + {(1, 0, 0): '+x', (-1, 0, 0): '-x', (0, 1, 0): '+y', (0, -1, 0): '-y',
                     (0, 0, 1): '+z', (0, 0, -1): '-z'}[tuple(nrm)]


def settings_for(struct, survey, prefab, key):
    vals = survey.get(prefab, {})
    s = {}
    if struct == 'EPC_SCFuseBox':
        s['_threshold'] = {'default': 0.1505, 'type': 'f32 @20',
                           'meaning': 'Trip-threshold lever position 0..1. Threshold in P/s = clamp(floor(v * 1000), 0, '
                                      '999) (SCTick_FuseBox: int(value * roundingIntervals); the prefab lever has '
                                      'roundingIntervals 1000 and default 150). Default 0.1505 = 150 P/s (all 47 corpus '
                                      'records). To set T P/s write (T + 0.5) / 1000.'}
    if struct == 'EPC_SCPipeManualValve':
        s['_actionableValue'] = {'default': 1.0, 'type': 'f32 @20',
                                 'meaning': 'Valve opening 0..1 (1 = fully open: 96 of 99 corpus records; others 0.80, '
                                            '0.37, 0.93).'}
    col = G.default_color(prefab)
    top = sorted(((int(k), v) for k, v in vals.get('_col', {}).items()), key=lambda kv: -kv[1])[:5]
    off = {'EPC_SpaceshipComponent': 20, 'EPC_SCFuseBox': 24, 'EPC_SCPipeManualValve': 24}[struct]
    s['_col'] = {'default': col, 'type': f'u8 @{off}',
                 'meaning': "paint colour index; default = the prefab's _defaultPaintableColor (0 on power parts "
                            "and nanopipes, 200 on pipes)", 'corpus_top': top}
    return s


def main():
    val = json.load(open(os.path.join(HERE, 'power_validation.json'), encoding='utf-8'))
    stats, structs, survey = val['stats'], val['structs'], val['settings']
    out = {'cable_rules': cable_rules()}
    atomic_dump(out, OUT)
    for key, prefab, name, child_map in TARGETS:
        inf = G.info(prefab, False)
        size = list(inf['size'])
        h = hashes.part_hash(prefab)
        twin = (prefab + ' M') in G.DUMP
        hm = hashes.part_hash(prefab, True) if twin else None
        struct = struct_of(inf['cls'])
        if prefab in structs:
            seen = max(structs[prefab].items(), key=lambda kv: kv[1])[0]
            assert seen == struct, (prefab, seen, struct)
        st = stats.get(prefab, {})
        names = sim_port_names(key, inf['ports'], child_map)
        ports, node_to_name = {}, {}
        for (nm, kind, d, f, c, fa, i, t) in inf['ports']:
            ports[names[i]] = {'cell': list(c), 'face': list(f), 'dir': d, 'kind': kind,
                               'game_port': i, 'game_type': t}
            node_to_name[nm] = names[i]
        for (nm, a, nrm, face, outside) in inf['fluid']:
            en = end_name(nrm)
            ports[en] = {'cell': list(min(outside)), 'face': list(min(face)), 'dir': 'both', 'kind': 'fluid',
                         'cells': [list(x) for x in sorted(outside)], 'faces': [list(x) for x in sorted(face)],
                         'normal': list(nrm), 'end_type': 'decoupling' if a == 2 else 'pipe'}
            node_to_name[nm] = en
        e = {'name': name, 'prefab': prefab, 'hash': f'{h:016x}', 'mirrored_hash': f'{hm:016x}' if hm else None,
             'struct': struct, 'size': size, 'ports': ports,
             'settings': settings_for(struct, survey, prefab, key)}
        tc = G.twin_check(prefab)
        if tc is not None:
            e['twin_prefab_ports_are_x_reflection'] = tc
        # corpus summary (normal + twin instances)
        use, misses, ovl, n_inst = {}, {}, 0, {'normal': 0, 'twin': 0}
        for m in ('normal', 'twin'):
            s_ = st.get(m)
            if not s_:
                continue
            n_inst[m] = s_['instances']
            ovl += s_['overlap_instances']
            for pn, c in s_['ports'].items():
                u = use.setdefault(node_to_name.get(pn, pn), [0, 0, 0])
                u[0] += c.get('cable', 0); u[1] += c.get('contact', 0); u[2] += sum(c.values())
            for pn, c in s_['ends'].items():
                u = use.setdefault(node_to_name.get(pn, pn), [0, 0, 0])
                u[0] += c.get('joined', 0); u[2] += sum(c.values())
            for k2, v2 in s_['misses'].items():
                misses[k2] = misses.get(k2, 0) + v2
        n = n_inst['normal'] + n_inst['twin']
        confirmed = sum(1 for p in ports if use.get(p, [0, 0, 0])[0] + use.get(p, [0, 0, 0])[1] > 0)
        e['corpus'] = {
            'instances': n, 'normal': n_inst['normal'], 'twin': n_inst['twin'],
            'ports_confirmed': f'{confirmed}/{len(ports)}',
            'port_use': {p: (f'cable {u[0]} + contact {u[1]} of {u[2]}' if ports[p]['kind'] != 'fluid'
                             else f'joined {u[0]} of {u[2]}') for p, u in use.items()},
            'misses': sum(misses.values()), 'misses_by_cable_kind': misses, 'overlaps': ovl}
        conf, notes = CONF[key]
        e['confidence'] = conf
        e['notes'] = notes
        out[key] = e
        atomic_dump(out, OUT)
    print('wrote', OUT, len(out) - 1, 'parts + cable_rules')


if __name__ == '__main__':
    main()
