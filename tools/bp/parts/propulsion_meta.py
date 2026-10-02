"""IL2CPP metadata facts used by the propulsion study (read-only on the game files).

    python propulsion_meta.py

Prints
  1. the classes that declare a nested `Blueprint` type (48 in this build): exactly these have their own
     settings struct "<Class>+Blueprint+BlueprintData"; all others inherit their parent's
  2. the parent class of every part class used by the propulsion prefabs, and the struct that follows
  3. the serialized field names of EPC_SpaceshipComponent and a few part classes, in order

global-metadata.dat v39 layout facts found here (on top of ../il2cpp.py):
  typeDefinitions (76-byte records): +0 nameIndex, +8 byvalTypeIndex, +12 parentIndex (a TypeIndex; the
    parent is the type whose byvalTypeIndex equals it), +20 fieldStart, +36 nestedTypesStart,
    +56 u16 field_count, +60 u16 nested_type_count
  header section 11 = fieldDefinitions (10-byte records, +0 nameIndex); section 15 = nestedTypes (i32)
"""
import os, struct, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import il2cpp, hashes

CLASSES = ['EPC_SCThruster', 'EPC_SCGimbalThruster', 'EPC_SCGimbalController', 'EPC_SCDamagedLargeFuelThruster',
           'EPC_SCBallast', 'EPC_SCFloodlight', 'EPC_SCRimcoreTurbo', 'EPC_SCLavaSucker', 'EPC_SCExtendableDamper',
           'EPC_SCPipeElectricValve', 'EPC_SCElectricGate', 'EPC_SCRadar', 'EPC_SCGreenTrenchPump',
           'EPC_SCIceCreamFreezer', 'EPC_SCOutcastPolarAnchor', 'EPC_SCSolarShieldGenerator',
           'EPC_SCWindShieldGenerator', 'EPC_SCPlasmaGenerator', 'EPC_SCBomb', 'EPC_SCClimaBomb', 'EPC_SCDecoupler',
           'EPC_SCSpring']


class Meta(il2cpp.Metadata):
    def __init__(self):
        super().__init__()
        b = self.b
        self.secs = [struct.unpack_from('<3I', b, 8 + 12 * i) for i in range(31)]
        self.n_types = self.secs[il2cpp.TYPEDEFS][2]
        self.names = [self.type_name(i) for i in range(self.n_types)]
        self.byval = {}
        for i in range(self.n_types):
            self.byval.setdefault(self._i(i, 8), i)

    def _i(self, ti, off):
        return struct.unpack_from('<i', self.b, self.t_off + 76 * ti + off)[0]

    def _h(self, ti, off):
        return struct.unpack_from('<H', self.b, self.t_off + 76 * ti + off)[0]

    def index(self, name):
        return self.names.index(name)

    def parent(self, ti):
        return self.byval.get(self._i(ti, 12))

    def nested(self, ti):
        start, n = self._i(ti, 36), self._h(ti, 60)
        o = self.secs[15][0]
        return [self.names[struct.unpack_from('<i', self.b, o + 4 * (start + j))[0]] for j in range(n)] if start >= 0 else []

    def fields(self, ti):
        start, n = self._i(ti, 20), self._h(ti, 56)
        o = self.secs[11][0]
        return [self.string(struct.unpack_from('<I', self.b, o + 10 * (start + j))[0]) for j in range(n)] if start >= 0 else []

    def struct_for(self, ti):
        """The class whose Blueprint struct this class serializes with (itself or the nearest ancestor)."""
        while ti is not None:
            if 'Blueprint' in self.nested(ti):
                return self.names[ti]
            ti = self.parent(ti)
        return None


def main():
    m = Meta()
    own = sorted(m.names[i] for i in range(m.n_types) if 'Blueprint' in m.nested(i) and m.names[i].startswith('EPC_'))
    print(f'1. {len(own)} classes declare a nested Blueprint type:')
    print('   ' + ', '.join(own))
    print('\n2. part classes -> parent -> settings struct')
    for c in CLASSES:
        ti = m.index(c)
        chain = []
        p = m.parent(ti)
        while p is not None and len(chain) < 6:
            chain.append(m.names[p]); p = m.parent(p)
        s = m.struct_for(ti)
        print(f'   {c:34s} parents {" > ".join(chain[:3]):60s} struct {s}+Blueprint+BlueprintData {hashes.struct_hash(s):016x}')
    print('\n3. serialized fields (declaration order)')
    for c in ['EPC_SpaceshipComponent', 'EPC_SCThruster', 'EPC_SCGimbalThruster', 'EPC_SCGimbalController',
              'EPC_SCElectricGate', 'EPC_SCRadar']:
        print(f'   {c}: {", ".join(m.fields(m.index(c)))}')


if __name__ == '__main__':
    main()
