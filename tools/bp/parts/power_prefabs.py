"""Dumps the power / fluid / cable prefabs (and their mirrored "<name> M" twins) from the game assets.

    python power_prefabs.py          -> tools/bp/parts/power_prefab_dump.json

Same output format as ../prefab_dump.py (hierarchy, transforms, MonoBehaviour class + raw hex), but for
prefabs that file lacks: SC_LargeRechargeableBattery, SC_PowerNanocable and every mirrored twin
(twins are real GameObjects named "<prefab> M" in globalgamemanagers.assets). Read-only on the game.
"""
import json, os, struct
import UnityPy

GAME = r'C:\Program Files (x86)\Steam\steamapps\common\Approximately Up\ApproximatelyUp_Data'
HERE = os.path.dirname(os.path.abspath(__file__))

POWER = ['SmallDisposableBattery', 'MediumDisposableBattery', 'LargeDisposableBattery', 'SmallRechargeableBattery',
         'MediumRechargeableBattery', 'LargeRechargeableBattery', 'SolarPanel', 'AutohemisphereSolarPanel', 'DynamoBox',
         'PowerRouter', 'LargePowerRouter', 'FuseBox', 'PowerBlocker', 'PowerGenerationMeter', 'PowerUsageMeter']
FLUID = ['PipeFull', 'PipeHalf', 'PipeQuarter', 'PipeCorner', 'PipeThreeway', 'PipeCross', 'PipeManualValve',
         'PipeMeter', 'PipeElectricValve', 'PipeDecoupling']
FLUID += ['Nano' + n[0].lower() + n[1:] for n in FLUID]          # SC_NanopipeFull, ... (no corpus instances)
CABLES = ['DataCable', 'PowerCable', 'PowerNanocable', 'PlasmaCable']
WANTED = {'SC_' + n for n in POWER + FLUID + CABLES}
WANTED |= {w + ' M' for w in WANTED}


def main():
    env = UnityPy.load(os.path.join(GAME, 'globalgamemanagers.assets'))
    byid = {o.path_id: o for o in env.objects}
    script_names = {}

    def script(pid):
        if pid not in script_names:
            try:
                script_names[pid] = byid[pid].read().m_ClassName
            except Exception:
                script_names[pid] = f'?{pid}'
        return script_names[pid]

    def mono(o):
        raw = o.get_raw_data()
        s_fid, s_pid = struct.unpack_from('<iq', raw, 16)
        n = struct.unpack_from('<i', raw, 28)[0]
        body = raw[32 + ((n + 3) & ~3):]
        return (script(s_pid) if s_fid == 0 else f'ext{s_fid}:{s_pid}'), body

    def node(go_obj, path):
        go = go_obj.read()
        here = f'{path}/{go.m_Name}' if path else go.m_Name
        entry = {'path': here, 'active': bool(getattr(go, 'm_IsActive', True)), 'components': [],
                 'go_id': go_obj.path_id}
        children = []
        for c in go.m_Components:
            ptr = c.component if hasattr(c, 'component') else c
            o = byid.get(ptr.path_id)
            if o is None:
                continue
            t = o.type.name
            if t in ('Transform', 'RectTransform'):
                tr = o.read()
                p, r, s = tr.m_LocalPosition, tr.m_LocalRotation, tr.m_LocalScale
                entry['pos'] = [round(p.x, 5), round(p.y, 5), round(p.z, 5)]
                entry['rot'] = [round(r.x, 5), round(r.y, 5), round(r.z, 5), round(r.w, 5)]
                entry['scale'] = [round(s.x, 5), round(s.y, 5), round(s.z, 5)]
                children = [byid[ch.path_id].read().m_GameObject.path_id for ch in tr.m_Children if ch.path_id in byid]
            elif t == 'MonoBehaviour':
                cls, body = mono(o)
                entry['components'].append({'type': cls, 'hex': body.hex(), 'pid': o.path_id})
            else:
                entry['components'].append({'type': t, 'pid': o.path_id})
        out = [entry]
        for gid in children:
            if gid in byid:
                out += node(byid[gid], here)
        return out

    dump = {}
    for o in env.objects:
        if o.type.name != 'GameObject':
            continue
        try:
            name = o.read().m_Name
        except Exception:
            continue
        if name in WANTED and name not in dump:
            dump[name] = node(o, '')
    missing = sorted(WANTED - set(dump))
    json.dump({'prefabs': dump, 'missing': missing}, open(os.path.join(HERE, 'power_prefab_dump.json'), 'w'), indent=0)
    print(f'{len(dump)} prefabs dumped; not found: {missing}')


if __name__ == '__main__':
    main()
