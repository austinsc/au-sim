"""Dumps every part prefab (SC_*) from the game's assets: hierarchy, transforms and components.

    python prefab_dump.py            -> tools/bp/prefab_dump.json

The part prefabs live in globalgamemanagers.assets as ordinary GameObjects. Their MonoBehaviours
carry no type trees (IL2CPP build), so each one is given as its script class name plus the raw
serialized field bytes (hex) after the standard header; decode those per class.

Units: 1 grid cell = 0.125 m. A part's local origin is its geometric centre, so for a 2 x 1 x 2
block the cell centres sit at x, z = +-0.0625. Known component layouts so far:
  EPC_Renderer   floats: local position (3), euler rotation in degrees (3), scale (3), then a mesh id
  DOTSColliderBox  u32 0, centre (3 floats), rotation? (3), size (3 floats, metres), bevel radius
  EPC_Actionable_Knob  f32 default value, f32 x2 sensitivity, i32 roundingIntervals (steps), ...
Port children are named "Port ..." (e.g. "Port A" = input, "Port X" = output on logic blocks).
"""
import json, os, struct, sys
import UnityPy

GAME = r'C:\Program Files (x86)\Steam\steamapps\common\Approximately Up\ApproximatelyUp_Data'
HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    prefabs = set(json.load(open(os.path.join(HERE, 'prefabs.json'), encoding='utf-8')))
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
        entry = {'path': here, 'active': bool(getattr(go, 'm_IsActive', True)), 'components': []}
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
                entry['components'].append({'type': cls, 'hex': body.hex()})
            else:
                entry['components'].append({'type': t})
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
        if name in prefabs and name not in dump:
            dump[name] = node(o, '')
    missing = sorted(prefabs - set(dump))
    json.dump({'prefabs': dump, 'missing': missing}, open(os.path.join(HERE, 'prefab_dump.json'), 'w'), indent=0)
    print(f'{len(dump)} prefabs dumped; not found as GameObjects: {missing}')


if __name__ == '__main__':
    main()
