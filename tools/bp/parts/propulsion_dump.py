"""Dumps the propulsion / powered-consumer prefabs (and their mirrored " M" twins) from the game's assets.

    python propulsion_dump.py        -> tools/bp/parts/propulsion_prefabs.json

Same method and output layout as ../prefab_dump.py (which only covers the prefabs named in
prefabs.json): each GameObject node gives its path, its MonoBehaviours as script class name +
raw serialized bytes (hex), and the Transform as UnityPy reads it. The Transform values are NOT
reliable; use the transform each EPC_Renderer carries in its first 36 bytes instead (pos, euler
degrees, scale). This dump adds the prefabs the corpus never showed (large thrusters, nanogates,
...) and the " M" twins, so mirrored port positions can be read directly.

Read-only on the game folder.
"""
import json, os, struct, sys
import UnityPy

GAME = r'C:\Program Files (x86)\Steam\steamapps\common\Approximately Up\ApproximatelyUp_Data'
HERE = os.path.dirname(os.path.abspath(__file__))

KEYS = ('SmallElectricThruster MediumElectricThruster LargeElectricThruster ElectricLiftThruster '
        'BidirectionalElectricManeuveringThruster SmallManeuveringThruster MediumManeuveringThruster '
        'LargeManeuveringThruster SmallFuelThruster MediumFuelThruster LargeFuelThruster DamagedLargeFuelThruster '
        'SmallSolidFuelThruster AtmosphericThruster AtmosphericFan AtmosphericLiftFan DuctedFan Ballast '
        'GimbalController GimbalThruster SmallDamper MediumDamper LargeDamper '
        'Floodlight RimcoreTurbo LavaSucker ExtendableDamper PipeElectricValve NanopipeElectricValve '
        'SmallGate MediumGate LargeGate SmallNanogate MediumNanogate LargeNanogate PersonnelGate PersonnelNanogate '
        'RampGate RampNanogate Radar GreenTrenchPump IceCreamFreezer OutcastPolarAnchor SolarShieldGenerator '
        'WindShieldGenerator SmallPlasmaGenerator BombC4 TNTBox ClimaBomb DecouplerQuarter ElectricGate '
        # reference parts with known geometry (for checking the decoding)
        'Initializer Constant DataHub WirelessTransmitter FrameQuarterA PowerRouter SmallDisposableBattery').split()


def main():
    wanted = set()
    for k in KEYS:
        wanted |= {'SC_' + k, 'SC_' + k + ' M'}
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
                entry['components'].append({'type': cls, 'hex': body.hex(), 'path_id': ptr.path_id})
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
        if name in wanted and name not in dump:
            dump[name] = node(o, '')
    missing = sorted(wanted - set(dump))
    json.dump({'prefabs': dump, 'missing': missing}, open(os.path.join(HERE, 'propulsion_prefabs.json'), 'w'), indent=0)
    print(f'{len(dump)} prefabs dumped; not in the game assets: {missing}')


if __name__ == '__main__':
    main()
