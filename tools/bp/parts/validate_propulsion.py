"""Derives and validates the propulsion / powered-consumer parts; writes propulsion.json.

    python validate_propulsion.py            -> report on stdout, writes propulsion.json

Inputs: propulsion_prefabs.json (propulsion_dump.py), ../prefab_dump.json, the corpus
(propulsion_corpus.py), Localization.csv, the simulator's TYPES (engine.js via node), schemas.json.

Steps
 1. Decoder self-test: the prefab port-table decoder (propulsion_geom.py) run on the 43 logic parts must
    reproduce partdb.json exactly (sizes and port cells).
 2. Every target prefab: size + ports from the prefab, and its " M" twin prefab's ports compared with the
    reflection rule (dx -> w-1-dx, normal x flipped).
 3. Corpus check of every instance (normal and twin), placed with the model.py rule (stored cell = min
    corner of the rotated footprint):
      overlaps  other parts' footprints inside ours (cables; parts with a known size)
      cables    each cable cell next to the footprint that opens toward it: on a predicted port cell of
                the right kind (hit), of the wrong kind, or not on a port at all (miss)
      contacts  direct port-to-port contacts with any decoded part (port cell = other's face cell and back)
 4. Port names: the port table order is the game's port order, which is the simulator's `order`.
 5. Settings: the struct each prefab's records use in the corpus (or, with no records, the struct its
    class gets from the IL2CPP metadata class tree; see propulsion.md), field values seen.
"""
import collections, csv, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BP = os.path.join(HERE, '..')
ROOT = os.path.join(BP, '..', '..')
sys.path.insert(0, HERE)
sys.path.insert(0, BP)
import hashes
import propulsion_corpus as PC
import propulsion_geom as geom
import propulsion_place as P
import propulsion_params
import propulsion_meta

LOC = r'C:\Program Files (x86)\Steam\steamapps\common\Approximately Up\ApproximatelyUp_Data\StreamingAssets\Localization.csv'
OUT = os.path.join(HERE, 'propulsion.json')

# (key, prefab) - key = simulator type_id, or the prefab name for parts the simulator lacks
SIM_PARTS = [
    ('small_electric_thruster', 'SmallElectricThruster'), ('medium_electric_thruster', 'MediumElectricThruster'),
    ('large_electric_thruster', 'LargeElectricThruster'), ('electric_lift_thruster', 'ElectricLiftThruster'),
    ('bidirectional_maneuvering_thruster', 'BidirectionalElectricManeuveringThruster'),
    ('small_maneuvering_thruster', 'SmallManeuveringThruster'), ('medium_maneuvering_thruster', 'MediumManeuveringThruster'),
    ('large_maneuvering_thruster', 'LargeManeuveringThruster'), ('small_fuel_thruster', 'SmallFuelThruster'),
    ('medium_fuel_thruster', 'MediumFuelThruster'), ('large_fuel_thruster', 'LargeFuelThruster'),
    ('small_solid_fuel_thruster', 'SmallSolidFuelThruster'), ('atmospheric_thruster', 'AtmosphericThruster'),
    ('atmospheric_fan', 'AtmosphericFan'), ('atmospheric_lift_fan', 'AtmosphericLiftFan'), ('ducted_fan', 'DuctedFan'),
    ('ballast', 'Ballast'), ('rcs_controller', 'GimbalController'),
    ('floodlight', 'Floodlight'), ('rimcore_turbo', 'RimcoreTurbo'), ('lava_sucker', 'LavaSucker'),
    ('extendable_damper', 'ExtendableDamper'), ('pipe_electric_valve', 'PipeElectricValve'),
    ('nanopipe_electric_valve', 'NanopipeElectricValve'), ('small_gate', 'SmallGate'), ('medium_gate', 'MediumGate'),
    ('large_gate', 'LargeGate'), ('small_nanogate', 'SmallNanogate'), ('medium_nanogate', 'MediumNanogate'),
    ('large_nanogate', 'LargeNanogate'), ('personnel_gate', 'PersonnelGate'), ('personnel_nanogate', 'PersonnelNanogate'),
    ('ramp_gate', 'RampGate'), ('ramp_nanogate', 'RampNanogate'), ('radar', 'Radar'),
    ('green_trench_pump', 'GreenTrenchPump'), ('ice_cream_freezer', 'IceCreamFreezer'),
    ('outcast_polar_anchor', 'OutcastPolarAnchor'), ('solar_shield_generator', 'SolarShieldGenerator'),
    ('wind_shield_generator', 'WindShieldGenerator'), ('small_plasma_generator', 'SmallPlasmaGenerator'),
    ('bomb_c4', 'BombC4'), ('tnt_box', 'TNTBox'), ('clima_bomb', 'ClimaBomb'), ('decoupler_small', 'DecouplerQuarter'),
]
EXTRA_PARTS = ['GimbalThruster', 'SmallDamper', 'MediumDamper', 'LargeDamper', 'DamagedLargeFuelThruster', 'ElectricGate']

# Settings struct per part class. Classes with their own nested Blueprint type (IL2CPP metadata, 48 in
# this build) use it; every other class here derives straight from EPC_SpaceshipComponent (parentIndex
# in the metadata, see propulsion_meta.py) and so uses its settings-free struct. EPC_SCDamagedLargeFuelThruster
# derives from EPC_SCThruster.
OWN_STRUCT = {'EPC_SCThruster', 'EPC_SCGimbalController', 'EPC_SCGimbalThruster', 'EPC_SCGreenTrenchPump',
              'EPC_SCOutcastPolarAnchor', 'EPC_SCRadar'}
INHERITS = {'EPC_SCDamagedLargeFuelThruster': 'EPC_SCThruster', 'EPC_SCGimbalThruster': 'EPC_SCThruster'}

FIELD_MEANING = {
    '_col': 'paint colour index (cosmetic; 0xc8/0xc9 are the unpainted factory finishes)',
    '_reverseButton': "the 'Reversed Input' toggle button beside the input port: 0 off, 1 on (1 byte; the declared "
                      "4-byte width overlaps _col)",
    '_leverA': 'RCS Controller lever A (float 0..1)', '_leverB': 'RCS Controller lever B (float 0..1)',
    '_leverC': 'RCS Controller lever C (float 0..1)', '_leverD': 'RCS Controller lever D (float 0..1)',
    '_leverE': 'RCS Controller lever E (float 0..1)', '_leverF': 'RCS Controller lever F (float 0..1)',
    '_toggle': 'on/off toggle (bool, 1 byte; the declared 4-byte width overlaps the following bytes)',
    '_channel': 'RCS Thruster mode knob (float 0..1, 6 steps). Saved values are (2k+1)/12, i.e. the centres of 6 '
                'equal bins: mode k = floor(value*6). Corpus torque analysis (the thruster force about the ship '
                'centroid, in the pilot seat frame; ~89% consistent): modes 0/1 = yaw (torque -y/+y), 2/3 = pitch '
                '(+x/-x), 4/5 = roll (+z/-z), matching the controller inputs yaw/pitch/roll. Signs are tentative.',
    '_knob0Value': 'radar knob 0 (float 0..1)', '_knob1Value': 'radar knob 1 (float 0..1)',
    '_knob2Value': 'radar knob 2 (float 0..1)',
    '_mode': "radar mounting mode (bool, 1 byte): 'Mode: Wall' / 'Mode: Floor'",
    '_leverValue': 'polar anchor lever (float 0..1)',
}


def sim_types():
    js = "const {TYPES}=require('./engine.js'); process.stdout.write(JSON.stringify(TYPES))"
    out = subprocess.run(['node', '-e', js], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
    return json.loads(out.stdout)


def localization():
    rows = {}
    with open(LOC, encoding='utf-8') as f:
        for r in csv.reader(f):
            if r and r[0].startswith('SC_'):
                rows[r[0]] = r[1]
    return rows


def reflect(g):
    w = g['size'][0]
    ports = []
    for p in g['ports']:
        q = dict(p)
        q['face'] = [w - 1 - p['face'][0]] + p['face'][1:]
        q['cell'] = [w - 1 - p['cell'][0]] + p['cell'][1:]
        q['normal'] = [-p['normal'][0]] + p['normal'][1:]
        ports.append(q)
    return {'size': g['size'], 'ports': ports}


def same_ports(a, b):
    key = lambda g: [(tuple(p['cell']), tuple(p['normal']), p['kind'], p['dir']) for p in g['ports']]
    return a['size'] == b['size'] and key(a) == key(b)


# ---- step 1: decoder self-test on the logic parts ------------------------------------------------

def self_test():
    """Sizes, port cells, directions AND port order (partdb order = the game's port order) of all 43
    logic parts, decoded from their prefabs."""
    db = json.load(open(os.path.join(BP, 'partdb.json'), encoding='utf-8'))
    ok = bad = 0
    for t, v in db.items():
        g = geom.geometry(v['prefab'])
        want = [(tuple(p['cell']), p['dir']) for p in v['ports'].values()]
        if t == 'wireless_transmitter':          # partdb lists the one shared port twice (tx/rx)
            want = want[:1]
        got = [(tuple(p['cell']), p['dir']) for p in g['ports']]
        if g['size'] == v['size'] and got == want:
            ok += 1
        else:
            bad += 1
            print(f'  self-test MISMATCH {t}: size {g["size"]} vs {v["size"]}; {got} vs {want}')
    return ok, bad


# ---- step 3: corpus ------------------------------------------------------------------------------

DIRS = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]


def all_geometry():
    """part hash -> (prefab, mirrored, geometry or None, size) for every dumped prefab."""
    sizes = P.generic_sizes()
    out = {}
    d = geom.dump()
    for name in d:
        if name.endswith(' M'):
            continue
        try:
            g = geom.geometry(name)
        except ValueError:
            g = None
        size = tuple(g['size']) if g else sizes.get(name)
        out[hashes.part_hash(name)] = (name, False, g, size)
        if name + ' M' in d:
            try:
                gm = geom.geometry(name + ' M')
            except ValueError:
                gm = None
        else:
            gm = reflect(g) if g else None
        out[hashes.part_hash(name, True)] = (name, True, gm, size)
    return out


def bbox(size, origin, k):
    pl = P.placer(size, origin, k)
    w, h, d = size
    cs = [pl((x, y, z)) for x in (0, w - 1) for y in (0, h - 1) for z in (0, d - 1)]
    return tuple(min(c[a] for c in cs) for a in range(3)), tuple(max(c[a] for c in cs) for a in range(3))


def boxes_touch(a, b, margin=1):
    return all(a[0][i] - margin <= b[1][i] and b[0][i] - margin <= a[1][i] for i in range(3))


def world_ports(g, origin, k):
    """[(index, port cell, face cell, kind, dir)]"""
    pl = P.placer(g['size'], origin, k)
    return [(i, pl(tuple(p['cell'])), pl(tuple(p['face'])), p['kind'], p['dir']) for i, p in enumerate(g['ports'])]


def compatible(a_kind, a_dir, b_kind, b_dir):
    if a_kind != b_kind:
        return False
    if a_kind != 'data':
        return True
    return 'both' in (a_dir, b_dir) or {a_dir, b_dir} == {'in', 'out'}


def corpus_check(targets, G, bps):
    """targets: set of prefab names. -> {prefab: stats}"""
    st = {pf: {'inst': collections.Counter(), 'overlap_inst': 0, 'overlap_with': collections.Counter(),
               'cable_hit': collections.Counter(), 'cable_wrongkind': collections.Counter(),
               'cable_miss': collections.Counter(), 'contact': collections.Counter(),
               'contact_bad': collections.Counter(), 'port_ok': collections.defaultdict(set),
               'twin_hit': collections.Counter(), 'twin_miss': collections.Counter(),
               'examples': [], 'orients': collections.Counter()} for pf in targets}
    for bp in bps:
        parts = bp['parts']
        mine = [i for i, x in enumerate(parts) if x[0] in G and G[x[0]][0] in targets and x[2] in P.ORI]
        if not mine:
            continue
        cab = {}
        for h, c, k, sh, col, sx, data in parts:
            if h in P.CABLES and k in P.ORI:
                cab[c] = (P.CABLES[h], P.cable_open(k, sh))
        placed = []     # (idx, prefab, bbox) of every other sized part
        for i, (h, c, k, sh, col, sx, data) in enumerate(parts):
            if h in G and G[h][3] and k in P.ORI and h not in P.CABLES:
                placed.append((i, G[h][0], bbox(G[h][3], c, k)))
        for i in mine:
            h, c, k = parts[i][:3]
            pf, mir, g, size = G[h]
            s = st[pf]
            s['inst']['twin' if mir else 'normal'] += 1
            s['orients'][k] += 1
            fp = P.footprint(size, c, k)
            bb = bbox(size, c, k)
            # overlaps
            ov = collections.Counter()
            ov['cable'] = sum(1 for q in fp if q in cab)
            near = []
            for j, opf, obb in placed:
                if j == i or not boxes_touch(bb, obb):
                    continue
                near.append(j)
                if boxes_touch(bb, obb, 0):
                    oh, oc, ok_ = parts[j][:3]
                    n = len(fp & P.footprint(G[oh][3], oc, ok_))
                    if n:
                        ov[opf] += n
            if any(ov.values()):
                s['overlap_inst'] += 1
                for kk, vv in ov.items():
                    if vv:
                        s['overlap_with'][kk] += 1
            if g is None:
                continue
            wp = world_ports(g, c, k)
            pmap = {(cell, tuple(f - q for f, q in zip(face, cell))): (pi, kind, dr) for pi, cell, face, kind, dr in wp}
            # cables that open toward the part
            seen = set()
            for q in fp:
                for dv in DIRS:
                    n_ = (q[0] + dv[0], q[1] + dv[1], q[2] + dv[2])
                    if n_ in fp or n_ not in cab:
                        continue
                    inw = (-dv[0], -dv[1], -dv[2])
                    ckind, opens = cab[n_]
                    if inw not in opens or (n_, inw) in seen:
                        continue
                    seen.add((n_, inw))
                    if (n_, inw) in pmap:
                        pi, kind, dr = pmap[(n_, inw)]
                        if kind == ckind:
                            s['cable_hit'][kind] += 1
                            s['port_ok'][pi].add('cable')
                            if mir:
                                s['twin_hit'][kind] += 1
                        else:
                            s['cable_wrongkind'][f'{ckind} cable on {kind} port'] += 1
                    else:
                        s['cable_miss'][ckind] += 1
                        if mir:
                            s['twin_miss'][ckind] += 1
                        if len(s['examples']) < 12:
                            s['examples'].append((bp['name'], 'cable miss', ckind, n_, inw, c, k))
            # direct contacts with decoded ports of nearby parts
            for j in near:
                oh, oc, ok_ = parts[j][:3]
                og = G[oh][2]
                if not og:
                    continue
                for pi, cell, face, kind, dr in wp:
                    for qi, ocell, oface, okind, odr in world_ports(og, oc, ok_):
                        if cell == oface and ocell == face:
                            if compatible(kind, dr, okind, odr):
                                s['contact'][kind] += 1
                                s['port_ok'][pi].add('contact')
                            else:
                                s['contact_bad'][f'{kind}/{dr} vs {G[oh][0]} {okind}/{odr}'] += 1
    return st


# ---- settings ------------------------------------------------------------------------------------

def settings_seen(targets, G, bps, schemas):
    sname = {int(v['hash'], 16): k for k, v in schemas.items()}
    out = {pf: {'structs': collections.Counter(), 'fields': collections.defaultdict(collections.Counter)} for pf in targets}
    for bp in bps:
        for h, c, k, sh, col, sx, data in bp['parts']:
            if h in G and G[h][0] in targets and data is not None:
                pf = G[h][0]
                sn = sname.get(sx, f'{sx:016x}')
                out[pf]['structs'][sn] += 1
                sch = schemas.get(sn)
                if not sch:
                    continue
                for f, off, sz in sch['fields']:
                    if f in ('_guid', '_gt'):
                        continue
                    if f in ('_reverseButton', '_toggle', '_mode') and sz == 4:
                        sz = 1                     # bool: declared 4 bytes, the next field overlaps
                    out[pf]['fields'][f][data[off:off + sz].hex()] += 1
    return out


def _f32(hexv):
    import struct
    return round(struct.unpack('<f', bytes.fromhex(hexv))[0], 6)


# Defaults the corpus alone can't give (prefab actionable defaults; see propulsion.md "Settings").
PREFAB_DEFAULTS = {
    'EPC_SCThruster+Blueprint+BlueprintData': {'_reverseButton': 0},
    'EPC_SCGimbalController+Blueprint+BlueprintData': {**{f'_lever{c}': 1.0 for c in 'ABCDEF'}, '_toggle': 1},
    'EPC_SCGimbalThruster+Blueprint+BlueprintData': {'_channel': 0.0},
    'EPC_SCRadar+Blueprint+BlueprintData': {'_knob0Value': 0.0, '_knob1Value': 0.0, '_knob2Value': 0.4},
    'EPC_SCOutcastPolarAnchor+Blueprint+BlueprintData': {'_leverValue': 0.0},
}
BOOL_FIELDS = ('_reverseButton', '_toggle', '_mode')

# Hand-written notes per part (facts checked in the run; see propulsion.md for the evidence).
GATE_NOTE = ('Ports on the back face (z = -1), bottom row, at the +x end. The door/ramp moves when the state '
             'input changes; keep its swing clear. Nanogate = same geometry and ports as the gate of that size.')
PART_NOTES = {
    'small_electric_thruster': 'Ports on the bottom face (y = -1) at the z = 0 corner: power x = 0, throttle x = 1. Exhaust and heat zone along +y, '
                               'from the top face up (force on the ship is -y). Body/mount is the lower half (y 0-3); the upper part is the nozzle.',
    'medium_electric_thruster': 'Same layout as the small one, scaled: ports on the bottom face at the z = 0 corner (power x = 0, throttle x = 1); exhaust +y.',
    'large_electric_thruster': 'No corpus instances; prefab only. Same port layout as the small/medium electric thrusters (confirmed for those): '
                               'bottom face, z = 0 corner, power x = 0, throttle x = 1. Exhaust +y.',
    'electric_lift_thruster': 'In-game name "Electric Flat Thruster". Ports on the bottom face at the z = 0 corner (power x = 0, throttle x = 1); exhaust +y.',
    'bidirectional_maneuvering_thruster': 'No corpus instances; prefab only. Ports on the +x face (x = 4) at z = 0: power y = 5, force y = 6. '
                                          'Fires both ways along y (two heat zones, +y and -y) depending on the input sign.',
    'small_maneuvering_thruster': 'Ports on the +x face (x = 4) at z = 0: power y = 1, throttle y = 2. Exhaust and heat zone along -y.',
    'medium_maneuvering_thruster': 'Ports on the +x face (x = 4) at z = 0: power y = 1, throttle y = 2. Exhaust -y.',
    'large_maneuvering_thruster': 'No corpus instances; prefab only. Ports on the +x face (x = 8) at z = 0: power y = 1, throttle y = 2. Exhaust -y.',
    'small_fuel_thruster': ('Only ONE port exists: the throttle input on the bottom face at (2,-1,0). The prefab has no power port, although '
                            'Localization still lists Port1 "Requires {0} P/s" and the simulator models one ("power" is listed in absent_ports). '
                            'Corpus: 245 data-cable hits, zero power cables anywhere around 247 instances. The one miss and the one power cable '
                            "on the data port are both in the game's own MainMenuBlueprint.bp, built with an older two-port layout. "
                            'Exhaust +y; fuel arrives by pipe.'),
    'medium_fuel_thruster': 'Only the throttle input exists, bottom face at (2,-1,0); no power port (see small_fuel_thruster). Exhaust +y.',
    'large_fuel_thruster': 'No corpus instances; prefab only. Only the throttle input exists, bottom face at (2,-1,0); no power port. Exhaust +y.',
    'small_solid_fuel_thruster': 'Single power port on the +x face at mid height (8,15,4); it ignites once enough power is delivered. Exhaust -y.',
    'atmospheric_thruster': 'Ports on the top face (y = 8) at x = 0: power z = 4, throttle z = 5. Blows along -z (behind the part).',
    'atmospheric_fan': 'Ports on the top face (y = 8) at x = 0: power z = 4, speed z = 5. Blows along -z for positive input (signed input).',
    'atmospheric_lift_fan': 'In-game name "Atmospheric Flat Fan". Ports on the bottom face at the z = 0 corner (power x = 0, speed x = 1). Blows along +y.',
    'ducted_fan': ('Ports on the top face (y = 8) at the +z edge (z = 47): rotation x = 24, power x = 25, speed x = 26. Mount strip (JointsArea) is the '
                   '+z face for x 16-31. IRREGULAR: the duct is round (6 m across). All 6 corpus instances have frames and cables in the empty '
                   'corners of the 48x8x48 bounding box (z 44-47, x 0-12 and 35-47), hence the overlaps and the 36 cable "misses". Treat the '
                   'bounding box as occupied (safe over-approximation). The fan tilts with the rotation input, so its swept volume can leave the box. '
                   'Blows along -y at rotation 0.'),
    'ballast': 'Ports on the back face (z = -1), bottom row: power x = 4, buoyancy x = 5.',
    'rcs_controller': ('In-game name "RCS Controller" (prefab SC_GimbalController). All four ports on the front face (z = 4), bottom row: power x = 0, '
                       'roll x = 1, pitch x = 2, yaw x = 3. Drives up to 6 RCS Thrusters (SC_GimbalThruster) wirelessly.'),
    'floodlight': 'Ports on the back face (z = -1), bottom row: intensity x = 0, horizontal x = 1, vertical x = 2, power x = 3. The lamp head rotates.',
    'rimcore_turbo': 'No corpus instances; prefab only. Ports on the top face (y = 16) at z = 12: power x = 9, on x = 10.',
    'lava_sucker': ('In-game name "Lava Pumping Tank". No corpus instances; prefab only. Ports on the front face (z = 16) at x = 12: power y = 10, '
                    'length y = 11, on y = 12. Its intake pipe extends (length input).'),
    'extendable_damper': ('Ports on the front face (z = 8) at y = 6: power x = 5, extension x = 6. The leg extends out of the bottom face (-y) by up to '
                          '1.5 m (12 cells); keep that clear.'),
    'pipe_electric_valve': 'A 2x2x2 pipe piece. Ports on the top face (y = 2) at z = 1: open x = 0, power x = 1. The pipe ends are fuel connections, not cable ports.',
    'nanopipe_electric_valve': 'No corpus instances; prefab only. Same geometry and ports as the Pipe With Electric Valve.',
    'small_gate': GATE_NOTE, 'medium_gate': GATE_NOTE, 'large_gate': GATE_NOTE,
    'small_nanogate': 'No corpus instances; prefab only. ' + GATE_NOTE,
    'medium_nanogate': 'No corpus instances; prefab only. ' + GATE_NOTE,
    'large_nanogate': 'No corpus instances; prefab only. ' + GATE_NOTE,
    'personnel_gate': 'In-game name "Personnel Door". Ports on the back face (z = -1) at x = 7: power y = 0, state y = 1.',
    'personnel_nanogate': 'In-game name "Personnel Nanodoor". No corpus instances; prefab only. Same ports as the Personnel Door.',
    'ramp_gate': 'Ports on the back face (z = -1) at x = 31: power y = 4, state y = 5. The ramp swings out when opened.',
    'ramp_nanogate': 'In-game name "Nanoramp Gate". No corpus instances; prefab only. Same ports as the Ramp Gate.',
    'radar': 'Single power port on the front face (z = 4) at x = 0, y = 0. One power-cable "miss" in an autosave, one of 80 events.',
    'green_trench_pump': 'Single power port on the front face (z = 16) at (8,7).',
    'ice_cream_freezer': 'No corpus instances; prefab only. Single power port on the +x face at (8,0,0).',
    'outcast_polar_anchor': 'Single power port on the back face at (2,2,-1).',
    'solar_shield_generator': ('No corpus instances; prefab only. Ports on the front face (z = 8), bottom row: plasma x = 3, radius x = 4, '
                               'max_heat out x = 5. The plasma port is undirected in the game (kind 4); the simulator calls it plin.'),
    'wind_shield_generator': 'Ports on the front face (z = 8), bottom row: plasma x = 3, radius x = 4, max_wind out x = 5. Plasma port undirected in the game.',
    'small_plasma_generator': 'Ports on the front face (z = 8), bottom row: power x = 0, speed x = 1, plasma x = 2. Plasma port undirected in the game.',
    'bomb_c4': 'Single trigger input on the top face at (3,2,1).',
    'tnt_box': ('Not in this game build: no SC_TNTBox GameObject in globalgamemanagers.assets (its Localization rows are a demo leftover). '
                'Would-be hashes: SC_TNTBox 7ca51030c1cc7b8f, twin 7a465c630a077c20. Not placeable.'),
    'clima_bomb': 'No corpus instances; prefab only. 24x24x56. Single trigger input on the -x face at (-1,12,38).',
    'decoupler_small': ('Prefab SC_DecouplerQuarter, in-game "Decoupler Small". Single trigger input on the +x face at (4,0,3). Usually touches a '
                        'port directly (385 direct contacts, 59 cabled).'),
    'SC_GimbalThruster': ('In-game "RCS Thruster". No cable ports: it links wirelessly to the RCS Controller (rcs_controller) and has a built-in '
                          'single-use battery. Mode knob setting _channel. Exhaust/heat zone along -y.'),
    'SC_SmallDamper': 'No ports, no settings (EPC_SCSpring on the settings-free struct). No twin prefab.',
    'SC_MediumDamper': 'No ports, no settings. No twin prefab.',
    'SC_LargeDamper': 'No ports, no settings. No twin prefab.',
    'SC_DamagedLargeFuelThruster': ('Quest item ("Damaged Large Fuel Thruster"). No ports; class derives from EPC_SCThruster, so it saves the '
                                    'EPC_SCThruster struct. No corpus instances.'),
    'SC_ElectricGate': ('Not in this game build: no SC_ElectricGate GameObject or Localization row. The gates use the EPC_SCElectricGate '
                        'class (small/medium/large gate, nanogates, personnel and ramp gates).'),
}


def confidence(st_entry, n_ports):
    n = sum(st_entry['inst'].values())
    if n == 0:
        return 'medium'
    confirmed = len([i for i in range(n_ports) if st_entry['port_ok'].get(i)])
    events = sum(st_entry['cable_hit'].values()) + sum(st_entry['contact'].values())
    misses = sum(st_entry['cable_miss'].values()) + sum(st_entry['cable_wrongkind'].values())
    if confirmed == n_ports and st_entry['overlap_inst'] == 0 and misses <= max(1, events // 50):
        return 'high'
    return 'medium'


def main():
    global META
    META = propulsion_meta.Meta()
    bps = PC.load()
    schemas = json.load(open(os.path.join(BP, 'schemas.json'), encoding='utf-8'))
    TYPES = sim_types()
    loc = localization()
    have = geom.dump()

    print('== 1. decoder self-test on the 43 logic parts (partdb.json)')
    ok, bad = self_test()
    print(f'   {ok} match, {bad} mismatch')

    G = all_geometry()
    entries = [(k, 'SC_' + p) for k, p in SIM_PARTS] + [('SC_' + p, 'SC_' + p) for p in EXTRA_PARTS]
    targets = {pf for _, pf in entries if pf in have}

    print('\n== 2. prefabs, twins')
    twin_ok = {}
    for key, pf in entries:
        if pf not in have:
            print(f'   {pf}: NOT in the game assets')
            continue
        g = geom.geometry(pf)
        tw = pf + ' M'
        if tw in have:
            twin_ok[pf] = same_ports(geom.geometry(tw), reflect(g))
            print(f'   {pf:46s} size {g["size"]}  twin prefab: reflection rule {"holds" if twin_ok[pf] else "FAILS"}')
        else:
            twin_ok[pf] = None
            print(f'   {pf:46s} size {g["size"]}  no twin prefab')

    print('\n== 3. corpus check (stored cell = min corner of the rotated footprint)')
    st = corpus_check(targets, G, bps)
    sets = settings_seen(targets, G, bps, schemas)

    out = {}
    for key, pf in entries:
        sim = TYPES.get(key)
        e = {'name': loc.get(f'{pf}_Name'), 'prefab': pf}
        if pf not in have and key.startswith('SC_'):
            print(f'   {key}: no prefab in this build (not a simulator type; no entry written)')
            continue
        if pf not in have:
            e.update({'hash': None, 'mirrored_hash': None, 'struct': None, 'size': None, 'ports': {}, 'settings': {},
                      'corpus': {'instances': 0, 'ports_confirmed': '0/0', 'overlaps': 0}, 'confidence': 'none',
                      'notes': PART_NOTES.get(key, f'{pf} is not in this game build.')})
            out[key] = e
            print(f'   {key}: no prefab')
            continue
        g = geom.geometry(pf)
        cls = geom.main_component(pf)['type']
        struct_name = META.struct_for(META.index(cls)) + '+Blueprint+BlueprintData'      # IL2CPP class tree
        hard = (cls if cls in OWN_STRUCT else INHERITS.get(cls, 'EPC_SpaceshipComponent')) + '+Blueprint+BlueprintData'
        assert struct_name == hard, (pf, struct_name, hard)
        s = st[pf]
        seen = sets[pf]
        if seen['structs']:
            corpus_struct = seen['structs'].most_common(1)[0][0]
            if corpus_struct != struct_name:
                print(f'   !! {pf}: corpus struct {corpus_struct} != class-derived {struct_name}')
                struct_name = corpus_struct
        e['hash'] = f'{hashes.part_hash(pf):016x}'
        e['mirrored_hash'] = f'{hashes.part_hash(pf, True):016x}' if pf + ' M' in have else None
        e['struct'] = struct_name
        e['size'] = g['size']
        # ports, named by the simulator's order (= the game's port order = the prefab's port table order)
        ports, absent = {}, []
        order = sim['order'] if sim else [f'port{i}' for i in range(len(g['ports']))]
        if sim and len(order) != len(g['ports']):
            print(f'   !! {key}: simulator has {len(order)} ports {order}, prefab {len(g["ports"])}')
        for i, name in enumerate(order):
            if i >= len(g['ports']):
                absent.append(name)
                continue
            p = g['ports'][i]
            if sim:
                want_kind = sim['kinds'].get(name, 'data')
                want_dir = 'in' if name in sim['inputs'] else 'out' if name in sim['outputs'] else 'both'
                if want_kind != p['kind'] or (p['kind'] == 'data' and want_dir != p['dir']):
                    print(f'   !! {key}.{name}: simulator {want_kind}/{want_dir}, prefab {p["kind"]}/{p["dir"]}')
            ports[name] = {'cell': p['cell'], 'face': p['face'], 'dir': p['dir'], 'kind': p['kind'],
                           'game_port': i, 'prefab_node': p['node']}
        e['ports'] = ports
        if absent:
            e['absent_ports'] = absent
        # settings
        sch = schemas.get(struct_name, {'fields': []})
        sett = {}
        for f, off, sz in sch['fields']:
            if f in ('_guid', '_gt'):
                continue
            nbytes = 1 if f in BOOL_FIELDS + ('_col',) else sz
            vals = seen['fields'].get(f)
            if f == '_col':
                default, src = geom.default_paint(pf), 'prefab _defaultPaintableColor'
            elif f in PREFAB_DEFAULTS.get(struct_name, {}):
                default, src = PREFAB_DEFAULTS[struct_name][f], 'prefab'
            elif vals:
                top = vals.most_common(1)[0][0]
                default, src = (bytes.fromhex(top)[0] if nbytes == 1 else _f32(top)), 'corpus mode'
            else:
                default, src = (0 if nbytes == 1 else 0.0), 'zero'
            item = {'offset': off, 'bytes': nbytes, 'default': default, 'default_source': src,
                    'meaning': FIELD_MEANING.get(f, '')}
            if vals:
                item['corpus_values'] = {(str(bytes.fromhex(k2)[0]) if nbytes == 1 else str(_f32(k2))): v2
                                         for k2, v2 in vals.most_common(8)}
            sett[f] = item
        e['settings'] = sett
        n_inst = sum(s['inst'].values())
        confirmed = len([i for i in range(len(g['ports'])) if s['port_ok'].get(i)])
        e['corpus'] = {'instances': n_inst, 'ports_confirmed': f'{confirmed}/{len(g["ports"])}', 'overlaps': s['overlap_inst'],
                       'normal': s['inst']['normal'], 'twin': s['inst']['twin'], 'orientations_seen': len(s['orients']),
                       'cable_hits': dict(s['cable_hit']), 'twin_cable_hits': dict(s['twin_hit']),
                       'twin_cable_misses': dict(s['twin_miss']), 'direct_contacts': dict(s['contact']),
                       'cable_misses': dict(s['cable_miss']), 'cable_wrong_kind': dict(s['cable_wrongkind']),
                       'bad_contacts': dict(s['contact_bad']), 'overlap_with': dict(s['overlap_with'])}
        e['confidence'] = 'medium' if key == 'ducted_fan' else confidence(s, len(g['ports']))
        e['notes'] = PART_NOTES.get(key, '')
        ex = geom.exhaust(pf)
        if ex:
            e['exhaust'] = {'dir': [list(d) for d in ex['dir']], 'heat_zones': ex['heat']}
            if 'blow' in ex:
                e['exhaust']['blow_zone'] = ex['blow']
        gp = propulsion_params.params(pf)
        if gp:
            e['game_params'] = gp
        e['twin_reflection_verified'] = twin_ok.get(pf)
        out[key] = e
        print(f'   {key:36s} {e["confidence"]:6s} inst {n_inst:4d} (n {s["inst"]["normal"]}, M {s["inst"]["twin"]}; twin hits {dict(s["twin_hit"])} misses {dict(s["twin_miss"])}) ports {confirmed}/{len(g["ports"])} '
              f'overlap {s["overlap_inst"]} {dict(s["overlap_with"])} hit {dict(s["cable_hit"])} contact {dict(s["contact"])} '
              f'miss {dict(s["cable_miss"])} wrong {dict(s["cable_wrongkind"])} badcontact {dict(s["contact_bad"])}')
        for ex_ in s['examples'][:3]:
            print('        e.g.', ex_)
    return out


def write_json(res):
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(res, f, indent=1, ensure_ascii=False)
    json.load(open(tmp, encoding='utf-8'))            # still valid
    os.replace(tmp, OUT)


if __name__ == '__main__':
    res = main()
    write_json(res)
    print('\nwrote', OUT, f'({len(res)} entries)')
