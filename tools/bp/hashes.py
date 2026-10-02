"""The game's blueprint name hash, recovered from GameAssembly.dll (see NOTES.md, "Hash scheme").

Every 64-bit id in a .bp file is BurstUtility.AsciiHash64(name):
  part hash    prefab name: "SC_Constant"; its mirrored twin is "SC_Constant M"
  struct hash  settings struct's .NET Type.FullName: "EPC_SCConstant+Blueprint+BlueprintData"
  field hash   C# field name: "_guid", "_gt", "_col", "_value", ...

AsciiHash64 is xxHash64-like (seed 0, xxHash64 primes and avalanche), but it is not real xxHash64:
  * it hashes one byte per char (the low byte of each UTF-16 code unit) ...
  * ... while the initial length term is the UTF-16 byte length (2 x chars)
  * it consumes 8 chars per round with the 8-byte-lane step, then single chars with the 1-byte step;
    there is no 32-byte stripe path and no 4-byte step
"""

M = (1 << 64) - 1
P1, P2, P3, P4, P5 = 0x9E3779B185EBCA87, 0xC2B2AE3D27D4EB4F, 0x165667B19E3779F9, 0x85EBCA77C2B2AE63, 0x27D4EB2F165667C5


def _rotl(x, r):
    return ((x << r) | (x >> (64 - r))) & M


def ascii_hash64(s):
    n = 2 * len(s)                  # the game's length term counts UTF-16 bytes
    h = (n + P5) & M
    i = 0                           # index in UTF-16 bytes, as in the game's loop
    while i + 16 <= n:              # 8 chars -> one little-endian u64 lane
        k = 0
        for j, c in enumerate(s[i // 2:i // 2 + 8]):
            k |= (ord(c) & 0xFF) << (8 * j)
        h ^= (_rotl((k * P2) & M, 31) * P1) & M
        h = (_rotl(h, 27) * P1 + P4) & M
        i += 16
    while i < n:                    # remaining chars, one byte each
        h ^= ((ord(s[i // 2]) & 0xFF) * P5) & M
        h = (_rotl(h, 11) * P1) & M
        i += 2
    h ^= h >> 33
    h = (h * P2) & M
    h ^= h >> 29
    h = (h * P3) & M
    h ^= h >> 32
    return h


def part_hash(prefab, mirrored=False):
    """prefab: e.g. 'SC_Constant'. Mirrored twins are separate prefabs named '<prefab> M'."""
    return ascii_hash64(prefab + ' M' if mirrored else prefab)


def struct_hash(component):
    """component: the EPC class, e.g. 'EPC_SCConstant' -> its nested Blueprint.BlueprintData struct."""
    return ascii_hash64(component + '+Blueprint+BlueprintData')


def field_hash(name):
    return ascii_hash64(name)


# Known values taken from saved blueprints; `python hashes.py` checks them.
_VECTORS = {
    'SC_Constant': 0x9fe80f5af364c2ec, 'SC_Constant M': 0xcee813dc3421e693, 'SC_DataCable': 0xe60658e2e04f33ce,
    'EPC_SCConstant+Blueprint+BlueprintData': 0x4bebf2e4eb16d986, 'EPC_SCCable+Blueprint+BlueprintData': 0xac55b0d723fc7373,
    '_guid': 0x5a9afb0dddc03646, '_gt': 0x674a096805f65dc6, '_actionableLabel': 0x602a2eadf84c5000,
    '_col': 0xa02a12ac78f009a6, '_labelRotated': 0x0ebcc5a8415a16fe,
}

if __name__ == '__main__':
    bad = {s: f'{ascii_hash64(s):016x}' for s, h in _VECTORS.items() if ascii_hash64(s) != h}
    print('all known vectors match' if not bad else f'MISMATCH: {bad}')
