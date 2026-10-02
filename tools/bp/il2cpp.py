"""Find a game method's machine code in GameAssembly.dll (IL2CPP, metadata v39 / Unity 6).

    python il2cpp.py BurstUtility.AsciiHash64            # token + address
    python il2cpp.py BurstUtility.AsciiHash64 --disasm   # plus dumpbin disassembly

How: global-metadata.dat holds names and tokens but no code. A method record (30 B in v39) gives
its name, declaring type and token. Assembly-CSharp's Il2CppCodeGenModule in GameAssembly.dll
holds methodPointers[], indexed by token RID - 1. That module is found through the pointer to its
"Assembly-CSharp.dll" name string. Burst-compiled code lives elsewhere, in
Plugins/x86_64/lib_burst_generated.dll, which ships with a PDB, so dumpbin names its functions.
"""
import os, struct, subprocess, sys

GAME = r'C:\Program Files (x86)\Steam\steamapps\common\Approximately Up'
META = os.path.join(GAME, r'ApproximatelyUp_Data\il2cpp_data\Metadata\global-metadata.dat')
DLL = os.path.join(GAME, 'GameAssembly.dll')
DUMPBIN = r'C:\Program Files\Microsoft Visual Studio\18\Professional\VC\Tools\MSVC\14.51.36231\bin\Hostx64\x64\dumpbin.exe'
SECTIONS = 'stringLiteral stringLiteralData string events properties methods'.split()   # first six, in header order
TYPEDEFS = 19                                                                       # header slot of typeDefinitions


class Metadata:
    def __init__(self, path=META):
        b = self.b = open(path, 'rb').read()
        magic, version = struct.unpack_from('<Ii', b, 0)
        if magic != 0xFAB11BAF or version != 39:
            raise SystemExit(f'expected IL2CPP metadata v39, got {version}: record layouts below need checking')
        sec = lambda i: struct.unpack_from('<3I', b, 8 + 12 * i)      # (offset, size, count)
        self.str_off = sec(2)[0]
        self.m_off, m_size, self.m_count = sec(5)
        self.t_off, t_size, t_count = sec(TYPEDEFS)
        if m_size != 30 * self.m_count or t_size != 76 * t_count:
            raise SystemExit('unexpected method/type record sizes')

    def string(self, i):
        o = self.str_off + i
        return self.b[o:self.b.index(b'\0', o)].decode('utf-8', 'replace')

    def type_name(self, ti):
        return self.string(struct.unpack_from('<i', self.b, self.t_off + 76 * ti)[0])

    def methods(self, type_name, method_name):
        """-> [(token, parameterCount)] for Type.Method (all overloads)."""
        out = []
        for i in range(self.m_count):
            o = self.m_off + 30 * i
            name, decl = struct.unpack_from('<iH', self.b, o)
            if self.string(name) == method_name and self.type_name(decl) == type_name:
                token, = struct.unpack_from('<I', self.b, o + 18)
                nparams, = struct.unpack_from('<H', self.b, o + 28)
                out.append((token, nparams))
        return out


def method_pointers(module='Assembly-CSharp.dll', dll=DLL):
    """-> (image bytes, function(rid) -> code VA) for one code-gen module."""
    b = open(dll, 'rb').read()
    pe = struct.unpack_from('<I', b, 0x3c)[0]
    nsec, optsz = struct.unpack_from('<H', b, pe + 6)[0], struct.unpack_from('<H', b, pe + 20)[0]
    base = struct.unpack_from('<Q', b, pe + 48)[0]
    secs = [struct.unpack_from('<4I', b, pe + 24 + optsz + 40 * i + 8) for i in range(nsec)]   # vsize, va, rawsize, raw
    def off2va(off):
        return next(base + va + off - raw for vs, va, rs, raw in secs if raw <= off < raw + rs)
    def va2off(v):
        return next(raw + v - base - va for vs, va, rs, raw in secs if va <= v - base < va + max(vs, rs))
    name_va = off2va(b.find(b'\0' + module.encode() + b'\0') + 1)
    o = b.find(struct.pack('<Q', name_va))         # Il2CppCodeGenModule.moduleName
    count, = struct.unpack_from('<I', b, o + 8)
    table = va2off(struct.unpack_from('<Q', b, o + 16)[0])
    def code(rid):
        if not 0 < rid <= count:
            raise IndexError(rid)
        return struct.unpack_from('<Q', b, table + 8 * (rid - 1))[0]
    return code


def main():
    if len(sys.argv) < 2 or '.' not in sys.argv[1]:
        raise SystemExit(__doc__)
    type_name, method_name = sys.argv[1].rsplit('.', 1)
    hits = Metadata().methods(type_name, method_name)
    if not hits:
        raise SystemExit(f'{sys.argv[1]}: not found (nested types use their own simple name, e.g. Bursted.Foo)')
    code = method_pointers()
    for token, nparams in hits:
        va = code(token & 0xFFFFFF)
        print(f'{sys.argv[1]}({nparams} params)  token {token:#010x}  code {va:#x}')
        if '--disasm' in sys.argv and va:
            # IL2CPP functions end in int3 padding; 0x400 bytes covers small helpers
            out = subprocess.run([DUMPBIN, '/NOLOGO', '/DISASM:NOBYTES', f'/RANGE:{va:#x},{va + 0x400:#x}', DLL],
                                 capture_output=True, text=True).stdout
            print('\n'.join(l for l in out.splitlines() if l.startswith('  0')))


if __name__ == '__main__':
    main()
