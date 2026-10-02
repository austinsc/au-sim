"""Which end of a one-way valve faces the fuel source? (corpus statistics)

    python power_pipeflow.py

Builds the fuel network of every blueprint (parts joined end-to-end, pipe ends face to face), then for
every manual / electric valve follows the network from each of its two ends (without passing through
any valve) and records whether a tank (source) or a fuel consumer (fuel thruster) is reachable.
"""
import collections, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import power_world as W

VALVES = {'SC_PipeManualValve', 'SC_PipeElectricValve', 'SC_NanopipeManualValve', 'SC_NanopipeElectricValve'}
SOURCES = {'SC_BlueTank', 'SC_GreenTank', 'SC_RedTank'}
SINKS = {'SC_SmallFuelThruster', 'SC_MediumFuelThruster', 'SC_LargeFuelThruster'}


def main():
    res = collections.Counter()
    per = collections.defaultdict(collections.Counter)
    for f, recs in W.corpus():
        names = {W.G.BY_HASH.get(r[0], ('',))[0] for r in recs}
        if not names & VALVES:
            continue
        w = W.world(recs, cache=False)
        parts = w['parts']
        # end-to-end joins: (part, end name) -> (other part, other end name)
        face_owner = {}
        for p in parts:
            for name, a, nrm, face, outside in p.fluid:
                face_owner[frozenset(face)] = (p.idx, name)
        adj = collections.defaultdict(set)
        joins = {}
        for p in parts:
            for name, a, nrm, face, outside in p.fluid:
                o = face_owner.get(frozenset(outside))
                if o and o[0] != p.idx:
                    q = parts[o[0]]
                    back = next((e for e in q.fluid if e[0] == o[1]), None)
                    if back and back[4] == face:
                        adj[p.idx].add(o[0])
                        joins[(p.idx, name)] = o[0]
        for p in parts:
            if p.prefab not in VALVES:
                continue
            seen_by_end = {}
            for name, a, nrm, face, outside in p.fluid:
                start = joins.get((p.idx, name))
                found = set()
                if start is not None:
                    seen = {p.idx, start}; stack = [start]
                    while stack:
                        q = stack.pop()
                        pf = parts[q].prefab
                        if pf in SOURCES:
                            found.add('tank')
                        if pf in SINKS:
                            found.add('thruster')
                        if pf in VALVES:          # do not walk through other valves
                            continue
                        for n in adj[q]:
                            if n not in seen:
                                seen.add(n); stack.append(n)
                seen_by_end[name] = '+'.join(sorted(found)) or 'nothing'
            key = tuple(sorted(seen_by_end.items()))
            per[p.prefab + (' M' if p.mirrored else '')][key] += 1
    for k, v in per.items():
        print(k)
        for kk, n in v.most_common():
            print('   ', n, kk)


if __name__ == '__main__':
    main()
