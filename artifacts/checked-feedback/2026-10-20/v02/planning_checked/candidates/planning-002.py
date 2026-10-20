"""Breadth-first search planner for the spanner domain."""

ACTIONS = ["walk", "pickup_spanner", "tighten_nut"]


def _ground(state, objects):
    types = {}
    for name, typ in objects:
        types.setdefault(typ, set()).add(name)
    men = sorted(types.get("man", set()))
    locs = sorted(types.get("location", set()))
    spanners = sorted(types.get("spanner", set()))
    nuts = sorted(types.get("nut", set()))
    out = []
    if men:
        for s in locs:
            for e in locs:
                for m in men:
                    if s == e:
                        continue
                    if ("at", m, s) in state and ("link", s, e) in state:
                        out.append(("walk", (s, e, m)))
        for l in locs:
            for sp in spanners:
                for m in men:
                    if ("at", m, l) in state and ("at", sp, l) in state:
                        out.append(("pickup_spanner", (l, sp, m)))
        for l in locs:
            for sp in spanners:
                for m in men:
                    for n in nuts:
                        if (("at", m, l) in state and ("at", n, l) in state
                                and ("carrying", m, sp) in state
                                and ("useable", sp) in state
                                and ("loose", n) in state):
                            out.append(("tighten_nut", (l, sp, m, n)))
    return out


def _apply(state, name, params):
    st = set(state)
    if name == "walk":
        s, e, m = params
        st.discard(("at", m, s))
        st.add(("at", m, e))
    elif name == "pickup_spanner":
        l, sp, m = params
        st.discard(("at", sp, l))
        st.add(("carrying", m, sp))
    else:
        l, sp, m, n = params
        st.discard(("loose", n))
        st.discard(("useable", sp))
        st.add(("tightened", n))
    return frozenset(st)


def get_plan(objects, init, goal):
    start = frozenset(init)
    goals = set(goal)
    if goals <= start:
        return []
    seen = {start}
    frontier = [(start, [])]
    steps = 0
    max_steps = 1500000
    while frontier and steps < max_steps:
        steps += 1
        nxt = []
        for state, plan in frontier:
            if len(plan) >= 999:
                continue
            for name, params in _ground(state, objects):
                ns = _apply(state, name, params)
                if ns in seen:
                    continue
                seen.add(ns)
                np = plan + ["(%s %s)" % (name, " ".join(params))]
                if goals <= ns:
                    return np
                nxt.append((ns, np))
        frontier = nxt
    return []
