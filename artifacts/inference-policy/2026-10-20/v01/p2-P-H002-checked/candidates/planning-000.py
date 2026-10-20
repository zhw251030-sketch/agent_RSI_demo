"""Grounded forward-search STRIPS planner for the spanner domain.

Grounds the three action schemas directly from the supplied objects and the
declared types, then performs breadth-first search over states with a visited
set. Plans are returned as parenthesized strings in schema parameter order.
"""

LOC = "location"
MAN = "man"
NUT = "nut"
SPANNER = "spanner"


def _by_type(objects):
    t = {}
    for pair in objects:
        try:
            name, typ = pair[0], pair[1]
        except Exception:
            continue
        t.setdefault(str(typ), []).append(str(name))
    for v in t.values():
        v.sort()
    return t


def _apply(state, add, dele):
    nxt = set(state)
    nxt.difference_update(dele)
    nxt.update(add)
    return nxt


def _walk_actions(state, men, locs):
    out = []
    for m in men:
        here = [a[1] for a in state if a[0] == "at" and a[1] == m]
        for h in here:
            if h not in locs:
                continue
            for a in state:
                if a[0] == "link" and a[1] == h and a[2] in locs:
                    out.append(("walk", (h, a[2], m),
                                [("at", m, a[2])], [("at", m, h)]))
    return out


def _pickup_actions(state, men, spanners, locs):
    out = []
    for m in men:
        mloc = [a[1] for a in state if a[0] == "at" and a[1] == m]
        for s in spanners:
            sloc = [a[2] for a in state if a[0] == "at" and a[1] == s]
            for s2 in sloc:
                for l in mloc:
                    if l == s2 and l in locs:
                        out.append(("pickup_spanner", (l, s, m),
                                    [("carrying", m, s)], [("at", s, l)]))
    return out


def _tighten_actions(state, men, spanners, nuts, locs):
    out = []
    carrying = set(a[2] for a in state if a[0] == "carrying")
    usable = set(a[1] for a in state if a[0] == "useable")
    loose = set(a[1] for a in state if a[0] == "loose")
    for m in men:
        mloc = [a[1] for a in state if a[0] == "at" and a[1] == m]
        for n in nuts:
            if n not in loose:
                continue
            nloc = [a[2] for a in state if a[0] == "at" and a[1] == n]
            for l in mloc:
                if l not in nloc or l not in locs:
                    continue
                for s in sorted(carrying & usable):
                    out.append(("tighten_nut", (l, s, m, n),
                                [("tightened", n)],
                                [("loose", n), ("useable", s)]))
    return out


def _actions(state, types):
    return (_walk_actions(state, types.get(MAN, []), types.get(LOC, []))
            + _pickup_actions(state, types.get(MAN, []), types.get(SPANNER, []), types.get(LOC, []))
            + _tighten_actions(state, types.get(MAN, []), types.get(SPANNER, []),
                              types.get(NUT, []), types.get(LOC, [])))


def _fmt(name, params):
    return "(" + name + " " + " ".join(params) + ")"


def get_plan(objects, init, goal):
    types = _by_type(objects)
    start = frozenset(init)
    goals = frozenset(goal)
    if goals <= start:
        return []
    if not types.get(MAN) or not types.get(LOC):
        return []
    limit = 1000
    frontier = [(start, [])]
    seen = {start}
    while frontier:
        nxt = []
        for state, plan in frontier:
            for _name, params, add, dele in _actions(state, types):
                ns = _apply(state, add, dele)
                if ns in seen:
                    continue
                nplan = plan + [_fmt(_name, params)]
                if len(nplan) > limit:
                    return []
                if goals <= ns:
                    return nplan
                seen.add(ns)
                nxt.append((ns, nplan))
        if not nxt:
            return []
        frontier = nxt
    return []