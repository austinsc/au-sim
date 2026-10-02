"""Game parameters of the propulsion / consumer parts, read from their prefabs (bonus to the geometry).

    python propulsion_params.py

The part component serializes EPC_SpaceshipComponent's fields, then its own (field names and order from
the IL2CPP metadata, propulsion_meta.py). The base run ends 36 bytes after the port table
(_iconTexture2D PPtr, _uiPreviewBounds Vector3, _categories, _customProperties count 0, _propertiesMaterial),
so the class's own fields start at   ds = ports_offset + 4 + 20 * nports + 36.
Checked: classes without fields of their own (ClimaBomb, Decoupler) end exactly at ds, and the parses
below end exactly at the record length where the fields are all fixed-size.

EPC_SCThruster's field run has a variable-length array in the middle (_particleSystems), so its tail is
read from the end: _maxFuelConsumptionPerSecond, _explosionFuelAmount, _fuelCoughingSpeed,
_powerConsumptionPerSec (4 floats), 4 PPtrs (_ignitionRenderer Fwd/Bwd, _heat Fwd/Bwd), _solidFuelTime,
_solidFuelRequiredIgnitionPower, _solidFuelNSV (PPtr) = the last 84 bytes. EPC_SCGimbalThruster adds
_gimbalChannelKnob (PPtr) and _batteryCapacity after that.

Units are the game's own (power in P/s as the tooltips show it; force as stored).
"""
import os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import propulsion_geom as geom


def _ds(name):
    b = geom._bytes(name)
    p = geom.base_layout(name)['ports_offset']
    n = struct.unpack_from('<i', b, p)[0]
    return b, p + 4 + 20 * n + 36


def _f(b, o):
    return round(struct.unpack_from('<f', b, o)[0], 6)


def _thruster(b, ds, extra_tail=0):
    t = len(b) - 84 - extra_tail
    bidir, ftype = struct.unpack_from('<2i', b, ds)
    out = {'is_bidirectional': bool(bidir), 'force_type': ftype,
           'max_force': [_f(b, ds + 8 + 4 * i) for i in range(3)],
           'efficiency_space': _f(b, ds + 20), 'efficiency_atmosphere': _f(b, ds + 24), 'efficiency_water': _f(b, ds + 28),
           'acceleration_time': _f(b, ds + 32),
           'max_fuel_per_s': _f(b, t), 'power_ps': _f(b, t + 12)}
    st, ign = _f(b, t + 64), _f(b, t + 68)
    if st:
        out['solid_fuel_time'] = st
        out['solid_fuel_ignition_power'] = ign
    return out


def params(name):
    """dict of decoded parameters, or {} for classes not covered."""
    cls = geom.main_component(name)['type']
    b, ds = _ds(name)
    f = lambda o: _f(b, ds + o)
    if cls in ('EPC_SCThruster', 'EPC_SCDamagedLargeFuelThruster'):
        return _thruster(b, ds)
    if cls == 'EPC_SCGimbalThruster':
        out = _thruster(b, ds, extra_tail=16)
        out['battery_capacity'] = _f(b, len(b) - 4)
        return out
    if cls == 'EPC_SCElectricGate':
        return {'power_ps': f(0), 'accelerator_speed': f(4)}
    if cls == 'EPC_SCBallast':
        return {'power_ps': f(0), 'max_buoyancy': f(4), 'speed': f(8)}
    if cls in ('EPC_SCFloodlight', 'EPC_SCRimcoreTurbo', 'EPC_SCLavaSucker', 'EPC_SCGreenTrenchPump'):
        return {'power_ps': f(0)}
    if cls == 'EPC_SCExtendableDamper':          # 3 PPtrs, _absorption, _consumptionPerSec
        return {'absorption': f(36), 'power_ps': f(40)}
    if cls == 'EPC_SCPipeElectricValve':         # EPC_SCPipe fields first, then the valve's
        return {'fuel_capacity': f(0), 'fuel_stability_threshold': f(4), 'fuel_stability_speed': f(8),
                'power_ps': f(12), 'accelerator_speed': f(16)}
    if cls == 'EPC_SCIceCreamFreezer':
        return {'idle_power_ps': f(0), 'max_time_without_power': f(4)}
    if cls == 'EPC_SCOutcastPolarAnchor':
        return {'power_ps': f(0), 'max_charging_per_s': f(4), 'cables_damage_radius': f(8), 'cables_damage_per_s': f(12)}
    if cls in ('EPC_SCSolarShieldGenerator', 'EPC_SCWindShieldGenerator'):
        return {'min_radius': f(0), 'max_radius': f(4), 'accelerator_speed': f(8)}
    if cls == 'EPC_SCPlasmaGenerator':           # 2 PPtrs, _rotorMaxRotation (Vector3), ...
        return {'max_plasma': f(36), 'max_power_ps': f(40), 'accelerator_speed': f(44)}
    if cls == 'EPC_SCBomb':
        return {'delay': f(12), 'explosion_strength': f(16)}
    if cls == 'EPC_SCRadar':                     # 6 PPtrs first
        return {'power_ps': f(72)}
    if cls == 'EPC_SCGimbalController':          # 13 PPtrs first
        return {'power_ps': f(156)}
    if cls == 'EPC_SCSpring':
        return {'spring_max_distance': f(12), 'absorption': f(16)}
    return {}


if __name__ == '__main__':
    d = geom.dump()
    for name in sorted(d):
        if name.endswith(' M') or not d[name][0]['components']:
            continue
        try:
            p = params(name)
        except Exception as e:                   # other part families use other layouts
            continue
        if p:
            print(f'{name:46s} {geom.main_component(name)["type"]:32s} {p}')
