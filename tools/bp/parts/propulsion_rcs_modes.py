"""RCS Thruster mode knob (_channel) vs the torque it produces: groups modes into yaw/pitch/roll pairs.

    python propulsion_rcs_modes.py

For every blueprint with >= 4 RCS thrusters, torque = (thruster centre - volume centroid of all sized parts) x
force direction (+y local), expressed in the frame of the blueprint's only RCS controller / pilot seat / world.
Counts (mode, dominant torque axis) where one axis carries > 70% of |torque|. See propulsion.md, Settings.
"""
import collections, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import propulsion_place as P, propulsion_corpus as PC, hashes, validate_propulsion as V
bps = PC.load()
G = V.all_geometry()
H = {hashes.part_hash('SC_GimbalThruster'), hashes.part_hash('SC_GimbalThruster', True)}
CTL = {hashes.part_hash('SC_GimbalController'), hashes.part_hash('SC_GimbalController', True)}
SEAT = {hashes.part_hash('SC_Seat'), hashes.part_hash('SC_Seat', True)}
def inv(k):
    m = P.ORI[k]; return [[m[j][i] for j in range(3)] for i in range(3)]
for frame_name, FR in (('controller', CTL), ('seat', SEAT), ('world', None)):
    table = collections.Counter()
    for bp in bps:
        parts = bp['parts']
        rcs = [x for x in parts if x[0] in H and x[2] in P.ORI]
        if len(rcs) < 4: continue
        if FR:
            fr = [x for x in parts if x[0] in FR and x[2] in P.ORI]
            if len(fr) != 1: continue
            mi = inv(fr[0][2])
        else:
            mi = [[1,0,0],[0,1,0],[0,0,1]]
        tot = [0.0, 0.0, 0.0]; wsum = 0.0
        for h, c, k, sh, col, sx, data in parts:
            if h in G and G[h][3] and k in P.ORI and h not in P.CABLES:
                size = G[h][3]; lo, hi = V.bbox(size, c, k); vol = size[0]*size[1]*size[2]
                for a in range(3): tot[a] += vol * (lo[a] + hi[a] + 1) / 2
                wsum += vol
        cen = [t / wsum for t in tot]
        for h, c, k, sh, col, sx, data in rcs:
            mode = min(5, int(struct.unpack_from('<f', data, 16)[0] * 6))
            lo, hi = V.bbox((4, 4, 2), c, k)
            p = [(lo[a] + hi[a] + 1) / 2 - cen[a] for a in range(3)]
            f = P.rot(P.ORI[k], (0, 1, 0))
            tq = (p[1]*f[2] - p[2]*f[1], p[2]*f[0] - p[0]*f[2], p[0]*f[1] - p[1]*f[0])
            tq = P.rot(mi, tq)
            ax = max(range(3), key=lambda a: abs(tq[a]))
            if abs(tq[ax]) / (sum(abs(t) for t in tq) or 1) > 0.7:
                table[(mode, ('+' if tq[ax] > 0 else '-') + 'xyz'[ax])] += 1
    print('frame:', frame_name)
    for m in range(6):
        print('  mode', m, {k[1]: v for k, v in sorted(table.items()) if k[0] == m})
