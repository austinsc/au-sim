"""Fits orientation index -> rotation, using rosetta parts (canonical = orientation 16) in the corpus.

For each orientation index k, every proper rotation R and two anchoring rules are scored:
  fixed : world = origin + R·c                      (origin is the same physical cell)
  min   : world = origin + R·c − min_f R·f          (origin is the rotated footprint's min corner)
Score = cable cells on rotated port cells − 10 × cable cells inside the rotated footprint.
Writes tools/bp/orientations.json.
"""
import itertools, json, os, sys, collections
sys.path.insert(0, os.path.dirname(__file__))
import corpus

HERE = os.path.dirname(os.path.abspath(__file__))

def rotations():
    out = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1, -1), repeat=3):
            m = [[0] * 3 for _ in range(3)]
            for i in range(3): m[i][perm[i]] = signs[i]
            det = (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                   + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
            if det == 1: out.append(tuple(tuple(r) for r in m))
    return out

def apply(m, c): return tuple(sum(m[i][j] * c[j] for j in range(3)) for i in range(3))

def main():
    res = json.load(open(os.path.join(HERE, 'parts.json'), encoding='utf-8'))
    shapes = {}
    for t, v in res.items():
        w, d = v['size_xz']
        foot = [(x, 0, z) for x in range(w) for z in range(d)]
        shapes[int(v['hash'], 16)] = (foot, [tuple(p) for p in v['ports']])
    R = rotations(); assert len(R) == 24
    bps = corpus.load()
    score = collections.defaultdict(lambda: collections.Counter()); count = collections.Counter()
    for bp in bps:
        cab = {c for h, c, r, sh, fl in bp if h == corpus.CABLE}
        for h, c, k, sh, fl in bp:
            if h not in shapes: continue
            foot, ports = shapes[h]; count[k] += 1
            for ri, m in enumerate(R):
                rf = [apply(m, f) for f in foot]
                mn = tuple(min(q[i] for q in rf) for i in range(3))
                for anchor, off in (('fixed', (0, 0, 0)), ('min', mn)):
                    w = lambda q: (c[0] + q[0] - off[0], c[1] + q[1] - off[1], c[2] + q[2] - off[2])
                    s = sum(w(apply(m, p)) in cab for p in ports) - 10 * sum(w(q) in cab for q in rf)
                    score[k][(ri, anchor)] += s
    table = {}
    for k in sorted(score):
        ranked = score[k].most_common()
        (ri, anchor), best = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0
        table[k] = {'rotation': R[ri], 'anchor': anchor, 'instances': count[k], 'score': best, 'runner_up': second}
        print(f'orientation {k:2d}: n={count[k]:4d}  R={R[ri]}  anchor={anchor:5s}  score {best:5d} vs {second:5d}')
    json.dump({str(k): v for k, v in table.items()}, open(os.path.join(HERE, 'orientations.json'), 'w'), indent=1)

if __name__ == '__main__':
    main()
