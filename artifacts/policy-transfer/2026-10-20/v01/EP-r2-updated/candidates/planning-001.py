"""Planner for the spanner domain.

Only the stated domain rules are used: `link` is DIRECTED and the reverse
link is never assumed.  Each tighten_nut consumes one `useable` spanner, so
every goal nut needs its own trip: walk along directed links to a location
holding a still-`useable` spanner, pick it up, walk along directed links to
the nut, tighten.  Because links are one-way, some instances may only be
partially solvable; in that case we emit the longest legal prefix that
maximises the number of tightened goal nuts instead of emitting illegal
actions or assuming reverse links.
"""


def get_plan(objects, init, goal):
    types = {}
    for pair in objects:
        name, t = pair[0], pair[1]
        types.setdefault(t, set()).add(name)
    men = sorted(types.get("man", set()))
    nuts = sorted(types.get("nut", set()))
    spanners = sorted(types.get("spanner", set()))
    locs = sorted(types.get("location", set()))

    state = set(tuple(f) for f in init)
    goalset = set(tuple(g) for g in goal)

    # DIRECTED adjacency only, from link facts in the current state.
    adj = dict((l, set()) for l in locs)
    for f in sorted(state):
        if f and f[0] == "link" and len(f) == 3:
            if f[1] in adj and f[2] in adj:
                adj[f[1]].add(f[2])

    plan = []

    def man_at():
        for m in men:
            for l in locs:
                if ("at", m, l) in state:
                    return (m, l)
        return (None, None)

    def locate(obj):
        for l in locs:
            if ("at", obj, l) in state:
                return l
        return None

    def path(src, dst):
        """Shortest directed path src -> dst, or None if unreachable."""
        if src == dst:
            return [src]
        prev = {src: None}
        frontier = [src]
        while frontier:
            nxt = []
            for u in frontier:
                for v in sorted(adj[u]):
                    if v not in prev:
                        prev[v] = u
                        nxt.append(v)
            frontier = nxt
        if dst not in prev:
            return None
        out = []
        c = dst
        while c is not None:
            out.append(c)
            c = prev[c]
        out.reverse()
        return out

    def walk(m, p):
        for i in range(len(p) - 1):
            plan.append("(walk %s %s %s)" % (p[i], p[i + 1], m))
            state.discard(("at", m, p[i]))
            state.add(("at", m, p[i + 1]))

    def pending_nuts():
        out = []
        for g in sorted(goalset):
            if g and g[0] == "tightened" and len(g) == 2 and g[1] in nuts:
                if ("tightened", g[1]) not in state and ("loose", g[1]) in state:
                    out.append(g[1])
        return out

    def usable_spanners():
        out = []
        for s in spanners:
            if ("useable", s) in state:
                sl = locate(s)
                if sl is not None:
                    out.append((s, sl))
        return out

    while len(plan) < 1000:
        todo = pending_nuts()
        if not todo:
            break
        m, ml = man_at()
        if m is None:
            break
        best = None
        for n in todo:
            nl = locate(n)
            if nl is None:
                continue
            p_mn = path(ml, nl)
            if p_mn is None:
                continue
            for (s, sl) in usable_spanners():
                p_ms = path(ml, sl)
                if p_ms is None:
                    continue
                p_sn = path(sl, nl)
                if p_sn is None:
                    continue
                cost = len(p_ms) + len(p_sn)
                if best is None or cost < best[0]:
                    best = (cost, n, nl, s, sl, p_ms, p_sn)
        if best is None:
            # No legal tighten is reachable right now: stop with a legal prefix.
            break
        _, n, nl, s, sl, p_ms, p_sn = best
        walk(m, p_ms)
        plan.append("(pickup_spanner %s %s %s)" % (sl, s, m))
        state.discard(("at", s, sl))
        state.add(("carrying", m, s))
        walk(m, p_sn)
        plan.append("(tighten_nut %s %s %s %s)" % (nl, s, m, n))
        state.discard(("loose", n))
        state.discard(("useable", s))
        state.add(("tightened", n))

    return plan[:1000]