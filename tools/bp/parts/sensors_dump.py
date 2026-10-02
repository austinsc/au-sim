"""Dumps the sensor prefabs (normal + mirrored twin "<name> M") from the game's assets, read-only.

    python sensors_dump.py      -> tools/bp/parts/sensors_prefabs.json

Same format as tools/bp/prefab_dump.json ({'prefabs': {name: [node, ...]}, 'missing': [...]}), but it also
covers prefabs that the shared dump lacks: the mirrored twins (" M"), SC_Thermoscan, SC_RedTank,
SC_NanopipeMeter and SC_BaobaraInterferencemeter. Each node = {path, active, pos, rot, scale, components}
where a MonoBehaviour component is {type: script class, hex: serialized body}. Unlike the shared dump, each node
also records its GameObject path id ('go_id') and each component its path id ('id'), so that object references
(PPtr = i32 fileID, i64 pathID) inside a body can be resolved, e.g. a component's list of its ports. As in the shared dump,
the GameObject Transform positions are unreliable; use the transform inside each EPC_Renderer body.
"""
import json, os, struct
import UnityPy

GAME = r'C:\Program Files (x86)\Steam\steamapps\common\Approximately Up\ApproximatelyUp_Data'
HERE = os.path.dirname(os.path.abspath(__file__))

KEYS = ('Accelerometer Aerometer Altimeter Atmometer AxisRotometer Rotometer DistanceMeter Gravitymeter '
        'Inclinometer Massmeter Thermometer Thermoscan TrajectoryCurvatureMeter VelocityMeter Windmeter '
        'BlueTank GreenTank RedTank LongRangeDistanceMeter Magnetometer GyroLine SpaceGPS SpaceScanner '
        'FuelAnalyzer PipeMeter NanopipeMeter BaobaraInterferencemeter').split()
# reference parts whose ports are already known (partdb.json), dumped to check the frame convention
REFERENCE = ['SC_Initializer', 'SC_Initializer M', 'SC_Condition', 'SC_Condition M', 'SC_DataHub',
             'SC_DataHub M', 'SC_Remapper', 'SC_Remapper M', 'SC_Datameter', 'SC_Datameter M']


def wanted():
    out = []
    for k in KEYS:
        out += ['SC_' + k, 'SC_' + k + ' M']
    return out + REFERENCE


def main():
    names = set(wanted())
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
                entry['components'].append({'type': cls, 'hex': body.hex(), 'id': o.path_id})
            else:
                entry['components'].append({'type': t, 'id': o.path_id})
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
        if name in names and name not in dump:
            dump[name] = node(o, '')
    missing = sorted(names - set(dump))
    json.dump({'prefabs': dump, 'missing': missing},
              open(os.path.join(HERE, 'sensors_prefabs.json'), 'w', encoding='utf-8'), indent=0)
    print(f'{len(dump)} prefabs dumped; not found: {missing}')


if __name__ == '__main__':
    main()
