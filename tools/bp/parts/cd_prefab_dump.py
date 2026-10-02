"""Dumps the controls/displays/cameras/monitors prefabs that tools/bp/prefab_dump.json lacks.

    python cd_prefab_dump.py        -> tools/bp/parts/cd_prefab_extra.json

prefab_dump.json (shared, read-only here) holds only prefabs listed in prefabs.json, i.e. the ones
seen in the corpus. This adds, in the same format:
  * prefabs never seen in the corpus (SC_HorizontalMeter, SC_LeverHorizontal, SC_Speaker,
    SC_MonitorLargeLCD, SC_MonitorLargeHologram)
  * every mirrored twin "<prefab> M" of these parts (the twins are real GameObjects in
    globalgamemanagers.assets), so twin port positions can be checked directly
  * the list of all SC_* GameObject names, to tell which twins exist at all
Same reading code as tools/bp/prefab_dump.py (UnityPy; MonoBehaviours as class name + raw hex).
"""
import json, os, struct, sys
import UnityPy

GAME = r'C:\Program Files (x86)\Steam\steamapps\common\Approximately Up\ApproximatelyUp_Data'
HERE = os.path.dirname(os.path.abspath(__file__))

KEYS = ('Button SmallButton Switch SmallSwitch StickSwitch TNTController LeverVertical LeverVerticalHalf '
        'LeverHorizontal SmallKnob JoystickHorizontal JoystickVertical Joystick2D Joystick3D Arc90Meter '
        'Arc270Meter HorizontalMeter VerticalMeter Beeper Speaker ColoredLightController LargeDatameter LEDText '
        'RedAlertLight BrakingPointSystem ETASystem Camera NightVisionCamera ZoomCamera RotationalTelescope '
        'CameraOverlay MonitorCRT MonitorSmallLCD MonitorMediumLCD MonitorLargeLCD MonitorSmallHologram '
        'MonitorMediumHologram MonitorLargeHologram Seat Whiteboard ColoredLight SmallToggleableLight').split()


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

    want = set()
    for k in KEYS:
        want.add('SC_' + k)
        want.add('SC_' + k + ' M')
    have = json.load(open(os.path.join(os.path.dirname(HERE), 'prefab_dump.json'), encoding='utf-8'))['prefabs']
    dump, all_sc = {}, []
    for o in env.objects:
        if o.type.name != 'GameObject':
            continue
        try:
            name = o.read().m_Name
        except Exception:
            continue
        if name.startswith('SC_'):
            all_sc.append(name)
        if name in want and name not in have and name not in dump:
            dump[name] = node(o, '')
    missing = sorted(want - set(dump) - set(have))
    json.dump({'prefabs': dump, 'missing': missing, 'all_sc_gameobjects': sorted(all_sc)},
              open(os.path.join(HERE, 'cd_prefab_extra.json'), 'w'), indent=0)
    print(f'{len(dump)} prefabs dumped; not found as GameObjects: {missing}')


if __name__ == '__main__':
    main()
