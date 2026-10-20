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
    locset = set(locs)
    for m in men:
        # (at m l) -> location is a[2]
        here = [a[2] for a in state if a[0] == "at" and len(a) >= 3 and a[1] == m]
        for h in here:
            if h not in locset:
                continue
            for a in state:
                if a[0] == "link" and len(a) >= 3 and a[1] == h and a[2] in locset:
                    out.append(("walk", (h, a[2], m),
                                [("at", m, a[2])], [("at", m, h)]))
    return out


def _pickup_actions(state, men, spanners, locs):
    out = []
    locset = set(locs)
    for m in men:
        # (at m l) -> location is a[2]
        mloc = [a[2] for a in state if a[0] == "at" and len(a) >= 3 and a[1] == m]
        for s in spanners:
            # (at s l) -> location is a[2]
            sloc = [a[2] for a in state if a[0] == "at" and len(a) >= 3 and a[1] == s]
            for s2 in sloc:
                for l in mloc:
                    if l == s2 and l in locset:
                        out.append(("pickup_spanner", (l, s, m),
                                    [("carrying", m, s)], [("at", s, l)]))
    return out


def _tighten_actions(state, men, spanners, nuts, locs):
    out = []
    locset = set(locs)
    carrying = set(a[2] for a in state if a[0] == "carrying" and len(a) >= 3)
    usable = set(a[1] for a in state if a[0] == "useable" and len(a) >= 2)
    loose = set(a[1] for a in state if a[0] == "loose" and len(a) >= 2)
    for m in men:
        # (at m l) -> location is a[2]
        mloc = [a[2] for a in state if a[0] == "at" and len(a) >= 3 and a[1] == m]
        for n in nuts:
            if n not in loose:
                continue
            # (at n l) -> location is a[2]
            nloc = [a[2] for a in state if a[0] == "at" and len(a) >= 3 and a[1] == n]
            for l in mloc:
                if l not in nloc or l not in locset:
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
    try:
        types = _by_type(objects)
        start = set(init)
        goals = set(goal)
        if not (goals - start):
            return []
        if not types.get(MAN) or not types.get(LOC):
            return []
        limit = 1000
        from collections import deque
        queue = deque([(frozenset(start), [])])
        seen = {frozenset(start)}
        while queue:
            state, plan = queue.popleft()
            for _name, params, add, dele in _actions(state, types):
                ns = frozenset(_apply(state, add, dele))
                if ns in seen:
                    continue
                nplan = plan + [_fmt(_name, params)]
                if len(nplan) > limit:
                    return []
                if goals <= ns:
                    return nplan
                seen.add(ns)
                queue.append((ns, nplan))
        return []
    except Exception:
        return []
