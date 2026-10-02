"""Cable statistics for the cable kinds over the blueprint corpus (one pass, one world per blueprint).

    python power_cables.py            -> prints the tables, writes power_cables_stats.json

1. Settings bytes of EPC_SCCable per kind (_shape, _type).
2. Open-face rule: does each open face of a cell meet something it can connect to? Scored for the
   data-cable rule (straight: local +-z, corner: local +y/+z) and for every alternative corner pair,
   separately per kind.
3. Port kinds joined per cable kind (cable in a port cell, opening toward the part).
4. Network shape: links per cell (<= 2), ports per network, open faces meeting another cable kind.
5. Reach: chain distance from every cell to the nearest anchored cell. Game rule (power.md): an
   anchored cell is joined to a compatible port, or is a straight cell whose side touches an anchoring
   frame face; a cell is unanchored when that distance exceeds MAX_UNANCHORED_CELLS = 10.
   'lo' anchors = compatible ports only (subset of the game's); 'hi' = lo + straight cells with a side
   neighbour inside any frame footprint (superset: the game also needs an edge or a welded face).
"""
import collections, itertools, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import power_geom as G
import power_world as W

LOCAL_DIRS = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
PAIRS = [p for p in itertools.combinations(LOCAL_DIRS, 2) if W.add(p[0], p[1]) != (0, 0, 0)]
RULE = {0: ((0, 0, 1), (0, 0, -1)), 1: ((0, 1, 0), (0, 0, 1))}


class Stats:
    def __init__(self):
        self.settings = collections.defaultdict(collections.Counter)
        self.score = collections.defaultdict(collections.Counter)
        self.total = collections.Counter()
        self.joined = collections.defaultdict(collections.Counter)
        self.mismatched = collections.defaultdict(collections.Counter)
        self.nports = collections.defaultdict(collections.Counter)
        self.deg = collections.defaultdict(collections.Counter)
        self.cross = collections.Counter()
        self.chain_max = {'lo': collections.Counter(), 'hi': collections.Counter()}
        self.frame_free = collections.Counter()
        self.longest = []
        self.ff_p2p_len = collections.Counter()     # frame-free networks joining 2 ports: length -> n
        self.ff_stub_len = collections.Counter()    # frame-free networks joining 1 port: length -> n

    # 1 + 2
    def open_rule(self, w):
        cab = w['cables']
        port_at = collections.defaultdict(list)
        for p in w['parts']:
            for name, kind, d, face, pc, inward in p.ports:
                port_at[pc].append((kind, inward))
        world_rule = {c: set(cb.opens) for c, cb in cab.items()}
        for shape in (0, 1):
            cands = [RULE[0]] if shape == 0 else PAIRS
            for pair in cands:
                for c, cb in cab.items():
                    if cb.shape != shape:
                        continue
                    m = G.ORI[cb.rot]
                    op = {G.rot(m, o) for o in pair}
                    for d in op:
                        n = W.add(c, d)
                        nb = cab.get(n)
                        hit = False
                        if nb and nb.kind == cb.kind:
                            back = W.neg(d)
                            if nb.shape == shape:
                                hit = back in {G.rot(G.ORI[nb.rot], o) for o in pair}
                            else:
                                hit = back in world_rule[n]
                        if not hit and any(k in W.COMPAT[cb.kind] and inward == d for k, inward in port_at.get(c, ())):
                            hit = True
                        self.score[(cb.kind, shape)][pair] += hit
                        if pair == cands[0]:
                            self.total[(cb.kind, shape)] += 1

    # 3 + 4
    def networks(self, w, links, pl, comp, nets):
        for c, cb in w['cables'].items():
            self.settings[cb.kind][(cb.shape, cb.type)] += 1
            self.deg[cb.kind][len(links.get(c, ()))] += 1
            for d in cb.opens:
                nb = w['cables'].get(W.add(c, d))
                if nb and nb.kind != cb.kind:
                    self.cross[(cb.kind, nb.kind)] += 1
        per_net = collections.defaultdict(list)
        for c, lst in pl.items():
            kind = w['cables'][c].kind
            for pidx, name, pk, pd, ok in lst:
                if ok:
                    self.joined[kind][(pk, pd)] += 1
                    per_net[comp[c]].append((pidx, name))
                else:
                    self.mismatched[kind][pk] += 1
        for i, members in enumerate(nets):
            self.nports[w['cables'][members[0]].kind][len(per_net.get(i, ()))] += 1

    # 5
    def reach(self, f, w, links, pl, nets):
        frame_cells = {c for p in w['parts'] if p.cls in W.FRAME_CLASSES for c in p.foot}
        port_anchor = {c for c, lst in pl.items() if any(x[-1] for x in lst)}
        frame_anchor, touches = set(), set()
        for c, cb in w['cables'].items():
            side = [d for d in W.DIRS if d not in cb.opens and W.neg(d) not in cb.opens] if cb.shape == 0 else \
                [d for d in W.DIRS if d not in cb.opens]
            if any(W.add(c, d) in frame_cells for d in side):
                touches.add(c)
                if cb.shape == 0:
                    frame_anchor.add(c)
        for model, anchors in (('lo', port_anchor), ('hi', port_anchor | frame_anchor)):
            dist = {a: 0 for a in anchors}
            q = collections.deque(anchors)
            while q:
                c = q.popleft()
                for n in links.get(c, ()):
                    if n not in dist:
                        dist[n] = dist[c] + 1; q.append(n)
            for members in nets:
                mx = max(dist.get(c, 999) for c in members)
                self.chain_max[model][min(mx, 999)] += 1
                if model == 'lo' and not any(c in touches for c in members):
                    self.frame_free[min(mx, 999)] += 1
                    na = sum(1 for c in members if c in port_anchor)
                    if na == 2:
                        self.ff_p2p_len[len(members)] += 1
                    elif na == 1:
                        self.ff_stub_len[len(members)] += 1
                    if mx < 999:
                        self.longest.append((mx, len(members), w['cables'][members[0]].kind, os.path.basename(f)))


def main():
    S = Stats()
    for f, recs in W.corpus():
        w = W.world(recs, cache=False)
        if not w['cables']:
            continue
        links = W.cable_links(w)
        pl = W.port_links(w)
        comp, nets = W.components(w, links)
        S.open_rule(w)
        S.networks(w, links, pl, comp, nets)
        S.reach(f, w, links, pl, nets)
    out = {'settings': {k: {f'{a},{b}': n for (a, b), n in v.items()} for k, v in S.settings.items()}}
    print('== (_shape, _type) per kind')
    for k, v in S.settings.items():
        print(' ', k, sorted(v.items()))
    print('== open-face rule: open faces meeting a connectable neighbour')
    out['open_rule'] = {}
    for (kind, shape), sc in sorted(S.score.items()):
        n = S.total[(kind, shape)]
        best = sc.most_common(3)
        print(f'  {kind:6s} shape {shape}: rule {RULE[shape]} {sc[RULE[shape]]}/{n}   best 3: {best}')
        out['open_rule'][f'{kind}/shape{shape}'] = {'faces': n, 'rule_hits': sc[RULE[shape]],
                                                     'best': [[list(map(list, p)), s] for p, s in best]}
    print('== ports joined per cable kind', {k: dict(v) for k, v in S.joined.items()})
    print('== incompatible port at a cable end', {k: dict(v) for k, v in S.mismatched.items()})
    print('== links per cell', {k: dict(v) for k, v in S.deg.items()})
    print('== ports per network', {k: dict(sorted(v.items())) for k, v in S.nports.items()})
    print('== open face meets another kind', dict(S.cross))
    out['joined'] = {k: {f'{a}/{b}': n for (a, b), n in v.items()} for k, v in S.joined.items()}
    out['mismatched'] = {k: dict(v) for k, v in S.mismatched.items()}
    out['links_per_cell'] = {k: dict(v) for k, v in S.deg.items()}
    out['ports_per_network'] = {k: dict(v) for k, v in S.nports.items()}
    out['open_face_meets_other_kind'] = {f'{a}->{b}': n for (a, b), n in S.cross.items()}
    S.longest.sort(reverse=True)
    print('== reach: networks by max distance to the nearest anchor')
    for model in ('lo', 'hi'):
        print(f'  {model}:', sorted(S.chain_max[model].items())[:40])
    print('  frame-free (lo):', sorted(S.frame_free.items()))
    print('  longest frame-free:', S.longest[:10])
    print('  frame-free port-to-port lengths:', sorted(S.ff_p2p_len.items()))
    print('  frame-free one-port stub lengths:', sorted(S.ff_stub_len.items()))
    out['reach'] = {'chain_max_lo': dict(S.chain_max['lo']), 'chain_max_hi': dict(S.chain_max['hi']),
                    'frame_free_chain_max': dict(S.frame_free), 'longest_frame_free': S.longest[:15],
                    'frame_free_port_to_port_lengths': dict(sorted(S.ff_p2p_len.items())),
                    'frame_free_stub_lengths': dict(sorted(S.ff_stub_len.items()))}
    json.dump(out, open(os.path.join(HERE, 'power_cables_stats.json'), 'w'), indent=1, default=str)


if __name__ == '__main__':
    main()
