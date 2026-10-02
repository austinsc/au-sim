"""The cable answers for power.json["cable_rules"], with the corpus numbers from power_cables_stats.json
(written by power_cables.py) and the game-code findings (see power.md, "Cables")."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
BP = os.path.dirname(HERE)
sys.path.insert(0, BP)
import hashes


def _anchor_models():
    path = os.path.join(HERE, 'power_anchor_stats.json')
    if not os.path.exists(path):
        return None
    st = json.load(open(path, encoding='utf-8'))
    return {m: {'networks_over_10': v['networks_over_10'], 'files_over_10': v['files_over_10'],
                'networks_at_9_10_11_12': [v['networks_by_max_distance'].get(str(k), 0) for k in (9, 10, 11, 12)],
                'anchored_cells': v['anchored_cells']} for m, v in st.items()}


def cable_rules():
    cs = json.load(open(os.path.join(HERE, 'power_cables_stats.json'), encoding='utf-8'))
    orl = cs['open_rule']
    hits = lambda k: f"{orl[k]['rule_hits']}/{orl[k]['faces']}"
    alt = lambda k: orl[k]['best'][1][1] if len(orl[k]['best']) > 1 else None
    hi = {int(k): v for k, v in cs['reach']['chain_max_hi'].items()}
    ff = {int(k): v for k, v in cs['reach']['frame_free_chain_max'].items()}
    h = lambda p: f'{hashes.part_hash(p):016x}'
    return {
        'kinds': {
            'data': {'prefab': 'SC_DataCable', 'hash': h('SC_DataCable'), '_type': 0, 'max_power_ps': None,
                     'corpus_cells': sum(cs['settings']['data'].values())},
            'power': {'prefab': 'SC_PowerCable', 'hash': h('SC_PowerCable'), '_type': 1, 'max_power_ps': 150,
                      'corpus_cells': sum(cs['settings']['power'].values())},
            'power_nano': {'prefab': 'SC_PowerNanocable', 'hash': h('SC_PowerNanocable'), '_type': 2,
                           'max_power_ps': 400, 'corpus_cells': 0, 'in_game_name': 'Power Nanocable',
                           'notes': 'No corpus instance (unlocked by the "Package_Ascensia_NanopowerCables" package). '
                                    'The prefab SC_PowerNanocable exists in globalgamemanagers.assets; its EPC_SCCable '
                                    'has _type 2 and _maxPower 400 (power cable: 1 and 150). Same struct, shapes and '
                                    'orientations as every cable; not yet load-tested.'},
            'plasma': {'prefab': 'SC_PlasmaCable', 'hash': h('SC_PlasmaCable'), '_type': 3, 'max_power_ps': None,
                       'corpus_cells': sum(cs['settings']['plasma'].values())},
        },
        'struct': 'EPC_SCCable, 24 bytes: _guid @0 (16), _gt @16 (4), _shape @20, _type @21, _col @22 (1 each)',
        'q1_same_geometry': {
            'answer': "Yes. All cable kinds share EPC_SCCable and the data cable's open-face rule: _shape 0 = "
                      'straight, open at local +z and -z; _shape 1 = corner, open at local +y and +z; rotated by '
                      'the orientation code (1x1x1 cell, so the origin is the cell itself). Only _type differs: '
                      '0 data, 1 power, 2 power nano, 3 plasma (SpaceshipCableType; the game\'s '
                      'SCTypeCableCell_Singleton mesh tables are ordered Data, Power, PowerNano, Plasma and each '
                      "prefab's EPC_SCCable stores the same number). _col is paint. No corpus record has a _type "
                      'other than its prefab\'s.',
            'shape_type_counts': cs['settings'],
            'open_rule_hits': {'data straight': hits('data/shape0'), 'data corner': hits('data/shape1'),
                               'power straight': hits('power/shape0'), 'power corner': hits('power/shape1'),
                               'plasma straight': hits('plasma/shape0'), 'plasma corner': hits('plasma/shape1')},
            'best_alternative_corner_rule_hits': {'data': alt('data/shape1'), 'power': alt('power/shape1'),
                                                  'plasma': alt('plasma/shape1')},
            'method': 'An open face scores when its neighbour is a same-kind cable opening back, or a compatible '
                      'port whose port cell is this cell and whose inward direction is this face. All 15 possible '
                      'corner face pairs were scored; local +y/+z wins for every kind by a wide margin.',
            'connect_rule': 'Two cells connect only if both open toward each other AND have the same _type '
                            '(UpdateCellsAndPortsJob compares the neighbour\'s _type before the alignment test), so a '
                            'power cable never joins a nano power cable or a data cable directly. Corpus open faces '
                            f"meeting a cable of another kind: {cs['open_face_meets_other_kind']} (dead ends).",
        },
        'q2_port_kinds': {
            'rule': 'GarageUpdateCables.UpdateCellsAndPortsJob switches on SpaceshipElectricPort._setupType: '
                    'DataInput (0), DataOutput (1) and DataInOut (3) accept _type 0 only; Power (2) accepts _type 1 '
                    'or 2; Plasma (4) accepts _type 3 only; Unset (5), the pass-through ports of the frames with '
                    'ports, accepts any _type 0..3. The cable must sit in the port cell and open toward the part '
                    '(dot < -0.99).',
            'data': ['DataInput', 'DataOutput', 'DataInOut (Wireless Transmitter)', 'Unset (frame ports)'],
            'power': ['Power', 'Unset (frame ports)'],
            'power_nano': ['Power', 'Unset (frame ports)'],
            'plasma': ['Plasma', 'Unset (frame ports)'],
            'corpus_joins': cs['joined'],
            'corpus_incompatible_ends': cs['mismatched'],
            'ports_per_network': cs['ports_per_network'],
            'note': 'The 4 data-cable ends in power ports and 23 power-cable ends in data ports are dead ends '
                    '(no connection). The thrusters\' "Port Input Reverse Mode Button" renderer looks like a port '
                    'but is not one (absent from _electricPorts and Localization).',
        },
        'q3_nano': 'A separate prefab, SC_PowerNanocable (hash above), on EPC_SCCable with _type = 2 and the same '
                   '_shape/orientation rules as every cable. It joins Power and Unset ports only and connects only '
                   'to other _type-2 cells. Rated 400 P/s against 150 P/s for SC_PowerCable (prefab _maxPower; '
                   'Bulb_31: a cable burns out when the circuit\'s total consumption or generation exceeds it).',
        'q4_reach': {
            'rule': "A cable cell is ANCHORED if (a) it is joined to a compatible port (_anchorEntity = the port's "
                    'part), or (b) it is STRAIGHT (_shape 0) and one of its 4 side probes (perpendicular to the cable '
                    'axis, 0.0725 m from the cell centre) hits a frame (SCTypeFrame) face that is welded (_solidFaces '
                    'bit set; on a frame with ports, not at a port) or, for an unwelded face, hits within 0.08 m of '
                    "that face polygon's edge, i.e. the cable runs along the frame's border cells. Corner cells are "
                    'never frame-anchored. Every other cell is in range if an anchored cell of the same chain is at '
                    'most 10 cable steps away (MAX_UNANCHORED_CELLS = 10). Any cell out of range blocks Fly Mode '
                    '("Cannot enter Fly Mode because some cable cells are not anchored."); such blueprints still '
                    'save and load.',
            'limits': 'Stub held at one end: the anchored cell + 10 = 11 cells. Port-to-port with no frame support: '
                      '22 cells (every cell within 10 of an end); 21 leaves one cell of margin.',
            'code': 'UpdateCellsAndPortsJob sets _anchorEntity (port: the Parent of the port; frame: the frame, probed '
                    'only when _shape == 0) and _anchorRangeEntity/_anchorRangeDistance = self/0. UpdateAnchoringJob '
                    'walks _connectedFwd/_connectedBwd from every anchored cell for d = 1..10 (stops at d == 11 or at '
                    'another anchored cell) and keeps the minimum d. AreAllCableCellsAnchoredJob fails if any cell has '
                    '_anchorRangeEntity == Null. Constants from global-metadata.dat: MAX_UNANCHORED_CELLS = 10, '
                    'CABLE_CELL_SIZE = 0.125, MAX_MOUNT_DISTANCE = 4.2.',
            'corpus': {
                'networks_by_max_distance_ports_and_frame_sides': {k: hi[k] for k in sorted(hi)},
                'frame_free_networks_by_max_distance_ports_only': {k: ff[k] for k in sorted(ff)},
                'reading': f"Anchors = compatible ports + straight cells touching a frame (a superset of the game's "
                           f'anchors): {hi.get(10, 0)} networks reach exactly 10, only '
                           f'{sum(v for k, v in hi.items() if 10 < k < 999)} exceed it and {hi.get(999, 0)} have no '
                           f'anchor at all. The exceptions are the loose I/O stubs of one Workshop circuit ("Triple '
                           f'PID - All Hover", 12-18 cells held at one end), autosaves and three other saves.',
                'longest_frame_free': cs['reach']['longest_frame_free'][:6],
                'frame_free_port_to_port_lengths': cs['reach'].get('frame_free_port_to_port_lengths'),
                'frame_free_one_port_stub_lengths': cs['reach'].get('frame_free_stub_lengths'),
                'frame_face_models': _anchor_models(),
                'reading_frame_models': 'power_anchor.py applies the exact rule with each frame prefab\'s plain '
                                        'JointsArea polygons as its faces (near face, 0.08 m edge test, record '
                                        '_solidFaces): ports only -> 1691 networks exceed 10; + frame edge rule -> 46 '
                                        '(220 networks at exactly 10, 5 at 11); + welded faces -> 45; any straight cell '
                                        'touching a frame (upper bound) -> 38. The edge rule accounts for nearly all '
                                        'frame anchoring; the 8 networks between the edge model and the upper bound sit '
                                        'on curved/wedge frames (SC_FrameB etc., whose sloped face is not a JointsArea '
                                        'polygon) or on welded faces, where the face list/bit order is a structure-agent '
                                        'question.',
                'reading_lengths': 'Port-to-port cables that touch no frame: 106 networks of 21 cells and 3 of 22 '
                                   '(the code limit: every cell within 10 of an end), then nothing until four '
                                   'one-off saves of 26-32 cells. One-port stubs that touch no frame stop at 11 cells '
                                   'apart from the same Workshop/autosave exceptions.',
            },
        },
    }
