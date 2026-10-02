"""Derives and validates the power / fluid parts, then writes power.json.

    python validate_power.py        (set AU_SCRATCH to choose the corpus cache dir; PYTHONUTF8=1)

For every target part:
  * geometry from the prefab (power_geom.py): size, ports (cell just outside the face, face cell,
    kind, direction), pipe ends (2 x 2 face patches);
  * corpus check over all instances (normal and mirrored twin), in world cells (power_world.py):
      overlaps   - footprint cells shared with another placed part or a cable cell
      port use   - per predicted port: a compatible cable in the port cell opening toward the part,
                   or a facing compatible port of another part (direct contact), or covered / free
      misses     - cables next to the footprint that open toward it but not at a predicted port cell
      pipe ends  - another part's pipe end face-to-face with the predicted end
  * writes power.json (atomically, so the file is valid JSON at all times) and power_validation.json.
"""
import collections, json, os, struct, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
BP = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, BP)
import power_geom as G
import power_world as W
import hashes

# key, prefab, in-game name, {prefab port child: simulator port name}
TARGETS = [
    ('small_disposable_battery', 'SC_SmallDisposableBattery', 'Small Disposable Battery', {'Port P': 'power'}),
    ('medium_disposable_battery', 'SC_MediumDisposableBattery', 'Medium Disposable Battery', {'Port P': 'power', 'Port X': 'level'}),
    ('large_disposable_battery', 'SC_LargeDisposableBattery', 'Large Disposable Battery', {'Port P': 'power', 'Port X': 'level'}),
    ('small_rechargeable_battery', 'SC_SmallRechargeableBattery', 'Small Rechargeable Battery', {'Port P': 'power'}),
    ('medium_rechargeable_battery', 'SC_MediumRechargeableBattery', 'Medium Rechargeable Battery', {'Port P': 'power', 'Port X': 'level'}),
    ('large_rechargeable_battery', 'SC_LargeRechargeableBattery', 'Large Rechargeable Battery', {'Port P': 'power', 'Port X': 'level'}),
    ('solar_panel', 'SC_SolarPanel', 'Solar Panel', {'Port P': 'a', 'Port P (1)': 'b'}),
    ('autohemisphere_solar_panel', 'SC_AutohemisphereSolarPanel', 'Auto-Hemisphere Solar Panel', {'Port P': 'power'}),
    ('dynamo_box', 'SC_DynamoBox', 'Dynamo Box', {'Port P': 'power'}),
    ('power_router', 'SC_PowerRouter', 'Power Router', {'Port P': 'a', 'Port R': 'b', 'Port S': 'c', 'Port T': 'd'}),
    ('large_power_router', 'SC_LargePowerRouter', 'Large Power Router',
     {'Port P': 'a', 'Port R': 'b', 'Port S': 'c', 'Port T': 'd', 'Port P2': 'e', 'Port R2': 'f', 'Port S2': 'g', 'Port T2': 'h'}),
    ('fuse_box', 'SC_FuseBox', 'Fuse Box', {'Port P': 'a', 'Port R': 'b'}),
    ('power_blocker', 'SC_PowerBlocker', 'Power Blocker', {'Port I': 'block', 'Port P': 'a', 'Port R': 'b'}),
    ('power_generation_meter', 'SC_PowerGenerationMeter', 'Power Generation Meter', {'Port X': 'generation', 'Port P': 'power'}),
    ('power_usage_meter', 'SC_PowerUsageMeter', 'Power Usage Meter', {'Port X': 'usage', 'Port P': 'power'}),
    ('pipe_electric_valve', 'SC_PipeElectricValve', 'Pipe With Electric Valve', {'Port A': 'open', 'Port P': 'power'}),
    ('nanopipe_electric_valve', 'SC_NanopipeElectricValve', 'Nanopipe With Electric Valve', {'Port A': 'open', 'Port P': 'power'}),
    ('SC_PipeFull', 'SC_PipeFull', 'Pipe Full', {}),
    ('SC_PipeHalf', 'SC_PipeHalf', 'Pipe Half', {}),
    ('SC_PipeQuarter', 'SC_PipeQuarter', 'Pipe Quarter', {}),
    ('SC_PipeCorner', 'SC_PipeCorner', 'Pipe Corner', {}),
    ('SC_PipeThreeway', 'SC_PipeThreeway', 'Pipe Threeway', {}),
    ('SC_PipeCross', 'SC_PipeCross', 'Pipe Cross', {}),
    ('SC_PipeManualValve', 'SC_PipeManualValve', 'Pipe With Manual Valve', {}),
    ('SC_PipeMeter', 'SC_PipeMeter', 'Pipe Meter', {}),
    ('SC_PipeDecoupling', 'SC_PipeDecoupling', 'Pipe Decoupling', {}),
    ('SC_NanopipeFull', 'SC_NanopipeFull', 'Nanopipe Full', {}),
    ('SC_NanopipeHalf', 'SC_NanopipeHalf', 'Nanopipe Half', {}),
    ('SC_NanopipeQuarter', 'SC_NanopipeQuarter', 'Nanopipe Quarter', {}),
    ('SC_NanopipeCorner', 'SC_NanopipeCorner', 'Nanopipe Corner', {}),
    ('SC_NanopipeThreeway', 'SC_NanopipeThreeway', 'Nanopipe Threeway', {}),
    ('SC_NanopipeCross', 'SC_NanopipeCross', 'Nanopipe Cross', {}),
    ('SC_NanopipeManualValve', 'SC_NanopipeManualValve', 'Nanopipe With Manual Valve', {}),
    ('SC_NanopipeMeter', 'SC_NanopipeMeter', 'Nanopipe Meter', {}),
    ('SC_NanopipeDecoupling', 'SC_NanopipeDecoupling', 'Nanopipe Decoupling', {}),
]

DIR = {('power', 'both'): 'both', ('plasma', 'both'): 'both', ('data', 'in'): 'in', ('data', 'out'): 'out',
       ('data', 'both'): 'both'}


def compatible_contact(k1, d1, k2, d2):
    """Two ports facing each other connect when the kinds match (data: an output to an input)."""
    if 'universal' in (k1, k2):
        return True
    if k1 != k2:
        return False
    if k1 == 'data':
        return {d1, d2} in ({'in', 'out'}, {'both', 'in'}, {'both', 'out'}, {'both'})
    return True


def validate(bps, prefabs):
    """-> {prefab: {mirrored: stats}}"""
    stats = {p: {m: {'instances': 0, 'blueprints': set(), 'overlap_instances': 0, 'overlap_with': collections.Counter(),
                     'cable_in_footprint': 0, 'rots': collections.Counter(),
                     'ports': collections.defaultdict(collections.Counter),
                     'misses': collections.Counter(), 'foreign_port_into_face': collections.Counter(),
                     'ends': collections.defaultdict(collections.Counter)} for m in (False, True)} for p in prefabs}
    for f, recs in bps:
        if not any(G.BY_HASH.get(r[0], ('',))[0] in stats for r in recs):
            continue
        w = W.world(recs, cache=False)
        mine = [p for p in w['parts'] if p.prefab in stats]
        if not mine:
            continue
        cab = w['cables']
        port_by_cell = collections.defaultdict(list)       # port cell -> (part idx, kind, dir, face cell)
        for q in w['parts']:
            for name, kind, d, face, pc, inward in q.ports:
                port_by_cell[pc].append((q.idx, kind, d, face, name))
        for p in mine:
            s = stats[p.prefab][p.mirrored]
            s['instances'] += 1; s['blueprints'].add(f); s['rots'][p.rot] += 1
            # (a) overlaps
            others = set()
            for c in p.foot:
                for j in w['occ'][c]:
                    if j != p.idx:
                        others.add(j)
                if c in cab:
                    s['cable_in_footprint'] += 1
            if others:
                s['overlap_instances'] += 1
                for j in others:
                    q = w['parts'][j]
                    s['overlap_with'][q.prefab + (' M' if q.mirrored else '')] += 1
            # (b) ports
            predicted = set()
            for name, kind, d, face, pc, inward in p.ports:
                predicted.add((pc, inward))
                cb = cab.get(pc)
                if cb and inward in cb.opens:
                    res = 'cable' if kind in W.COMPAT[cb.kind] else f'cable_wrong_kind:{cb.kind}'
                else:
                    res = None
                    for j, k2, d2, face2, n2 in port_by_cell.get(face, ()):
                        if j != p.idx and face2 == pc:
                            res = 'contact' if compatible_contact(kind, d, k2, d2) else f'contact_wrong:{k2}/{d2}'
                            break
                    if res is None:
                        if w['occ'].get(pc):
                            res = 'covered'
                        elif cb:
                            res = 'cable_not_open'
                        else:
                            res = 'free'
                s['ports'][name][res] += 1
            # misses: cables beside the footprint that open into it, not at a predicted port
            for c in p.foot:
                for dvec in W.DIRS:
                    n = W.add(c, dvec)
                    if n in p.foot:
                        continue
                    cb = cab.get(n)
                    if cb and W.neg(dvec) in cb.opens and (n, W.neg(dvec)) not in predicted:
                        s['misses'][cb.kind] += 1
                    for j, k2, d2, face2, n2 in port_by_cell.get(c, ()):
                        if j != p.idx and face2 == n:
                            if (n, W.neg(dvec)) not in predicted:
                                s['foreign_port_into_face'][k2] += 1
            # (c) pipe ends
            for name, a, nrm, face, outside in p.fluid:
                res = 'open'
                occ = {j for c in outside for j in w['occ'].get(c, ()) if j != p.idx}
                for j in occ:
                    q = w['parts'][j]
                    for n2, a2, nrm2, face2, outside2 in q.fluid:
                        if face2 == outside and outside2 == face:
                            res = 'joined'
                            break
                    if res == 'joined':
                        break
                if res != 'joined' and occ:
                    res = 'blocked'
                s['ends'][name][res] += 1
    return stats


def settings_survey(bps, prefabs):
    vals = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    structs = collections.defaultdict(collections.Counter)
    for f, recs in bps:
        for h, sh, cell, rot, data, fields in recs:
            pm = G.BY_HASH.get(h)
            if not pm or pm[0] not in prefabs:
                continue
            structs[pm[0]][W.PC.STRUCT_NAME.get(sh, f'{sh:016x}')] += 1
            for fn, (o, sz) in fields.items():
                if fn in ('_guid', '_gt'):
                    continue
                if fn in ('_threshold', '_actionableValue'):
                    v = round(struct.unpack_from('<f', data, o)[0], 4)
                else:
                    v = data[o]
                vals[pm[0]][fn][v] += 1
    return structs, vals


def atomic_dump(obj, path):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.tmp')
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, indent=1)
    os.replace(tmp, path)


def main():
    bps = W.corpus()
    prefabs = {t[1] for t in TARGETS}
    stats = validate(bps, prefabs)
    structs, vals = settings_survey(bps, prefabs)
    out = {'stats': {}, 'structs': {k: dict(v) for k, v in structs.items()},
           'settings': {k: {fn: dict(c.most_common(12)) for fn, c in v.items()} for k, v in vals.items()}}
    for pf, by in stats.items():
        out['stats'][pf] = {}
        for m, s in by.items():
            if not s['instances']:
                continue
            out['stats'][pf]['twin' if m else 'normal'] = {
                'instances': s['instances'], 'blueprints': len(s['blueprints']),
                'overlap_instances': s['overlap_instances'], 'overlap_with': dict(s['overlap_with'].most_common(8)),
                'cable_in_footprint': s['cable_in_footprint'], 'rots': dict(s['rots']),
                'ports': {n: dict(c) for n, c in s['ports'].items()}, 'misses': dict(s['misses']),
                'foreign_port_into_face': dict(s['foreign_port_into_face']),
                'ends': {n: dict(c) for n, c in s['ends'].items()}}
    atomic_dump(out, os.path.join(HERE, 'power_validation.json'))
    for pf in sorted(out['stats']):
        for m, s in out['stats'][pf].items():
            print(f"{pf:28s} {m:6s} n={s['instances']:5d} bps={s['blueprints']:3d} ovl={s['overlap_instances']:4d} "
                  f"cab_in={s['cable_in_footprint']} misses={s['misses']} foreign={s['foreign_port_into_face']}")
            for n, c in s['ports'].items():
                print(f"      {n:12s} {c}")
            for n, c in s['ends'].items():
                print(f"      end {n:18s} {c}")
            if s['overlap_with']:
                print('      overlaps:', s['overlap_with'])
    print('structs', out['structs'])
    print('settings', json.dumps(out['settings'])[:3000])


if __name__ == '__main__':
    main()
