"""Places every corpus record in world cells (parts with prefab geometry + all cable kinds).

    world(recs) -> {'cables': {cell: Cable}, 'parts': [Part], 'occ': {cell: [part index]}, 'unknown': n}

Cable cells open at local +-z (shape 0, straight) or local +y/+z (shape 1, corner), rotated by the
orientation code (same rule as ../networks.py, here applied to all cable kinds).
"""
import collections, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import power_geom as G
import power_corpus as PC

H = lambda name: next(h for h, (p, m) in G.BY_HASH.items() if p == name and not m)
CABLE_KIND = {H('SC_DataCable'): 'data', H('SC_PowerCable'): 'power', H('SC_PlasmaCable'): 'plasma',
              H('SC_PowerNanocable'): 'nano'}
OPEN = {0: ((0, 0, 1), (0, 0, -1)), 1: ((0, 1, 0), (0, 0, 1))}
DIRS = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
FRAME_CLASSES = {'EPC_SCFrame', 'EPC_SCFramePipe', 'EPC_SCFrameWithPorts'}
# which port kinds a cable kind can join (game: GarageUpdateCables.UpdateCellsAndPortsJob jump table on
# SpaceshipElectricPort._setupType; 'universal' = Unset frame-with-ports port, accepts any cable)
COMPAT = {'data': {'data', 'universal'}, 'power': {'power', 'universal'}, 'nano': {'power', 'universal'},
          'plasma': {'plasma', 'universal'}}

Cable = collections.namedtuple('Cable', 'kind shape rot opens col type')
Part = collections.namedtuple('Part', 'idx hash prefab mirrored cls origin rot size foot ports fluid rec')


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def neg(a):
    return (-a[0], -a[1], -a[2])


def cable_opens(shape, rot):
    m = G.ORI[rot]
    return tuple(G.rot(m, o) for o in OPEN.get(shape, ()))


_CACHE = {}


def world(recs, cache=True):
    if not cache:
        return _world(recs)
    key = id(recs)
    if key in _CACHE and _CACHE[key][0] is recs:
        return _CACHE[key][1]
    w = _world(recs)
    _CACHE[key] = (recs, w)
    return w


def _world(recs):
    cables, parts, unknown = {}, [], 0
    occ = collections.defaultdict(list)
    for i, (h, sh, cell, rot, data, fields) in enumerate(recs):
        if h in CABLE_KIND:
            shape, typ, col = data[20], data[21], data[22]
            cables[cell] = Cable(CABLE_KIND[h], shape, rot, cable_opens(shape, rot), col, typ)
            continue
        pm = G.BY_HASH.get(h)
        inf = G.info(*pm) if pm else None
        if inf is None or rot not in G.ORI:
            unknown += 1
            continue
        size = inf['size']
        foot = G.footprint(size, cell, rot)
        m = G.ORI[rot]
        wp = []
        for name, kind, d, face, pc, fa, *_ in inf['ports']:
            wp.append((name, kind, d, G.place(size, cell, rot, face), G.place(size, cell, rot, pc), neg(G.rot(m, fa))))
        fl = []
        for name, a, nrm, face, outside in inf['fluid']:
            fl.append((name, a, G.rot(m, nrm), {G.place(size, cell, rot, q) for q in face},
                       {G.place(size, cell, rot, q) for q in outside}))
        p = Part(len(parts), h, pm[0], pm[1], inf['cls'], cell, rot, size, foot, wp, fl, i)
        parts.append(p)
        for c in foot:
            occ[c].append(p.idx)
    return {'cables': cables, 'parts': parts, 'occ': occ, 'unknown': unknown}


def cable_links(w):
    """Mutual-open connections between cable cells of the same kind -> {cell: [neighbour cells]}."""
    cab = w['cables']
    links = collections.defaultdict(list)
    for c, cb in cab.items():
        for d in cb.opens:
            n = add(c, d)
            nb = cab.get(n)
            if nb and nb.kind == cb.kind and neg(d) in nb.opens:
                links[c].append(n)
    return links


def port_links(w):
    """Cable cells joined to part ports: {cell: [(part idx, port name, port kind, port dir, compatible?)]}.

    A cable joins a port when it sits in the port cell and opens toward the part (inward direction)."""
    cab = w['cables']
    out = collections.defaultdict(list)
    for p in w['parts']:
        for name, kind, d, face, pc, inward in p.ports:
            cb = cab.get(pc)
            if cb and inward in cb.opens:
                out[pc].append((p.idx, name, kind, d, kind in COMPAT[cb.kind]))
    return out


def components(w, links):
    comp = {}
    nets = []
    for c in w['cables']:
        if c in comp:
            continue
        stack = [c]; comp[c] = len(nets); members = [c]
        while stack:
            q = stack.pop()
            for n in links.get(q, ()):
                if n not in comp:
                    comp[n] = len(nets); stack.append(n); members.append(n)
        nets.append(members)
    return comp, nets


def corpus():
    return PC.load()
