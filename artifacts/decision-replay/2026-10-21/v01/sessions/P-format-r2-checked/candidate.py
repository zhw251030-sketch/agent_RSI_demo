"""Grounded BFS planner for the spanner STRIPS domain.

Grounds walk, pickup_spanner and tighten_nut from the declared objects, then
performs breadth-first search over atom sets. Returns parenthesized grounded
action strings in schema parameter order.
"""

LOC = "location"
MAN = "man"
NUT = "nut"
SPANNER = "spanner"


def _by_type(objects):
    t = {}
    try:
        items = list(objects)
    except Exception:
        items = []
    for pair in items:
        try:
            name, typ = pair[0], pair[1]
        except Exception:
            continue
        t.setdefault(str(typ), []).append(str(name))
    for v in t.values():
        v.sort()
    return t


def _norm(facts):
    out = set()
    try:
        it = list(facts)
    except Exception:
        return out
    for f in it:
        try:
            out.add(tuple(str(x) for x in f))
        except Exception:
            continue
    return out


def _loc_of(state, thing):
    return set(a[2] for a in state if a[0] == "at" and a[1] == thing)


def _actions(state, men, spanners, nuts, locs):
    locset = set(locs)
    carrying = set(a[2] for a in state if a[0] == "carrying")
    usable = set(a[1] for a in state if a[0] == "useable")
    loose = set(a[1] for a in state if a[0] == "loose")
    out = []
    for m in men:
        mloc = _loc_of(state, m) & locset
        # walk
        for a in state:
            if a[0] == "link" and a[2] in locset and a[1] in mloc:
                out.append(("walk", (a[1], a[2], m),
                            [("at", m, a[2])], [("at", m, a[1])]))
        # pickup_spanner
        for s in spanners:
            if s in carrying:
                continue
            shared = _loc_of(state, s) & mloc
            for l in shared:
                out.append(("pickup_spanner", (l, s, m),
                            [("carrying", m, s)], [("at", s, l)]))
        # tighten_nut
        if not mloc:
            continue
        for n in nuts:
            if n not in loose:
                continue
            nloc = _loc_of(state, n) & mloc
            for s in sorted(carrying & usable):
                for l in nloc:
                    out.append(("tighten_nut", (l, s, m, n),
                                [("tightened", n)],
                                [("loose", n), ("useable", s)]))
    return out


def _fmt(name, params):
    return "(" + " ".join([name] + list(params)) + ")"


def get_plan(objects, init, goal):
    types = _by_type(objects)
    start = frozenset(_norm(init))
    goals = frozenset(_norm(goal))
    if goals <= start:
        return []
    men = types.get(MAN, [])
    locs = types.get(LOC, [])
    spanners = types.get(SPANNER, [])
    nuts = types.get(NUT, [])
    if not men or not locs:
        return []
    frontier = [(start, [])]
    seen = {start}
    while frontier:
        nxt = []
        for state, plan in frontier:
            for name, params, add, dele in _actions(state, men, spanners, nuts, locs):
                ns = set(state)
                ns.difference_update(dele)
                ns.update(add)
                ns = frozenset(ns)
                if ns in seen:
                    continue
                nplan = plan + [_fmt(name, params)]
                if len(nplan) > 1000:
                    return []
                if goals <= ns:
                    return nplan
                seen.add(ns)
                nxt.append((ns, nplan))
        if not nxt:
            return []
        frontier = nxt
    return []
