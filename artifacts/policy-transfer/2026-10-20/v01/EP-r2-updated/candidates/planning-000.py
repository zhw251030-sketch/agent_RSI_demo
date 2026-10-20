"""Planner for the spanner domain.

Every loose goal nut consumes one `useable` spanner (tighten_nut deletes
useable), so each nut needs its own trip: fetch a useable spanner, carry it to
the nut, tighten.  Movement uses BFS over the link graph; we traverse a link
edge in either direction because otherwise the nut location is often a dead end
and the remaining nuts could never be reached.
"""


def get_plan(objects, init, goal):
    types = {}
    for name, t in objects:
        types.setdefault(t, set()).add(name)
    men = sorted(types.get("man", set()))
    nuts = sorted(types.get("nut", set()))
    spanners = sorted(types.get("spanner", set()))
    locs = sorted(types.get("location", set()))

    state = set(tuple(f) for f in init)
    goal = set(tuple(g) for g in goal)

    # undirected adjacency over link facts (never invents location pairs)
    adj = dict((l, set()) for l in locs)
    for f in sorted(state):
        if f[0] == "link" and f[1] in adj and f[2] in adj:
            adj[f[1]].add(f[2])
            adj[f[2]].add(f[1])

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
        if src == dst:
            return [src]
        prev = {src: None}
        q = [src]
        while q:
            nq = []
            for u in q:
                for v in sorted(adj[u]):
                    if v not in prev:
                        prev[v] = u
                        nq.append(v)
            q = nq
        if dst not in prev:
            return None
        p = []
        c = dst
        while c is not None:
            p.append(c)
            c = prev[c]
        p.reverse()
        return p

    def walk(m, p):
        for i in range(len(p) - 1):
            plan.append("(walk %s %s %s)" % (p[i], p[i + 1], m))
            state.discard(("at", m, p[i]))
            state.add(("at", m, p[i + 1]))

    def pending():
        res = []
        for g in sorted(goal):
            if g and g[0] == "tightened" and len(g) == 2 and g[1] in nuts:
                if ("tightened", g[1]) not in state and ("loose", g[1]) in state:
                    res.append(g[1])
        return res

    def free_spanners():
        out = []
        for s in spanners:
            if ("useable", s) in state:
                sl = locate(s)
                if sl is not None:
                    out.append((s, sl))
        return out

    while len(plan) < 1000:
        todo = pending()
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
            pn = path(ml, nl)
            if pn is None:
                continue
            for (s, sl) in free_spanners():
                ps = path(ml, sl)
                if ps is None:
                    continue
                pn2 = path(sl, nl)
                if pn2 is None:
                    continue
                cost = len(ps) + len(pn2)
                if best is None or cost < best[0]:
                    best = (cost, n, nl, s, sl, ps, pn2)
        if best is None:
            break
        _, n, nl, s, sl, ps, pn2 = best
        walk(m, ps)
        plan.append("(pickup_spanner %s %s %s)" % (sl, s, m))
        state.discard(("at", s, sl))
        state.add(("carrying", m, s))
        walk(m, pn2)
        plan.append("(tighten_nut %s %s %s %s)" % (nl, s, m, n))
        state.discard(("loose", n))
        state.discard(("useable", s))
        state.add(("tightened", n))

    return plan[:1000]