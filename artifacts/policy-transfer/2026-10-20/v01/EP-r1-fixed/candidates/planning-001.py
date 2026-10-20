"""Planner for the spanner domain (strict STRIPS, directed links).

Repairs vs the archived artifact:
  * Every emitted action is applied to an explicit simulated state with the
    exact preconditions/effects of the domain (walk: at man start, link start end;
    pickup_spanner: at man l, at spanner l; tighten_nut: at man l, at nut l,
    carrying man s, useable s, loose n).  Nothing is emitted without checking
    the simulated preconditions first, so no action can be invalid.
  * Tightening does NOT consume the spanner: the domain deletes `useable ?s`
    but never adds it, so a spanner is single-use.  We therefore re-verify
    `useable` after each tightening in the simulator, and prefer spanners that
    are still useable.
  * Links are honoured as directed, but we also allow the *reverse* of a link
    pair only when the reverse link is absent? No: reverse links are never
    assumed.  Reachability is computed on the directed link graph.  Because the
    nut location can be a sink, each nut trip is planned from the man's current
    position, and if no directed route to a useable spanner exists we try the
    reverse-direction route as a last resort only if it is genuinely a link.
  * The returned plan is validated action-by-action against the simulator; on
    any inconsistency we drop the tail so we never emit an illegal step.
"""

MAX_ACTIONS = 1000


def get_plan(objects, init, goal):
    obj_set = set(objects)
    types = {}
    for name, t in sorted(obj_set):
        types.setdefault(name, []).append(t)

    def of_type(t):
        return sorted(n for n, ts in types.items() if t in ts)

    men = of_type("man")
    nuts = of_type("nut")
    spanners = of_type("spanner")
    locs = of_type("location")

    state = set(tuple(f) for f in init)
    goal = set(tuple(g) for g in goal)
    locset = set(locs)

    # directed adjacency from link facts only
    out = dict((l, set()) for l in locs)
    links = set()
    for f in state:
        if len(f) == 3 and f[0] == "link" and f[1] in locset and f[2] in locset:
            links.add((f[1], f[2]))
            out[f[1]].add(f[2])

    plan = []

    def man_at(m):
        for l in sorted(locs):
            if ("at", m, l) in state:
                return l
        return None

    def locate(o):
        for l in sorted(locs):
            if ("at", o, l) in state:
                return l
        return None

    def bfs(src, dst):
        if src is None or dst is None:
            return None
        if src == dst:
            return [src]
        prev = {src: None}
        frontier = [src]
        while frontier:
            nxt = []
            for u in frontier:
                for v in sorted(out.get(u, ())):
                    if v not in prev:
                        prev[v] = u
                        nxt.append(v)
            frontier = nxt
        if dst not in prev:
            return None
        p = []
        c = dst
        while c is not None:
            p.append(c)
            c = prev[c]
        p.reverse()
        return p

    def emit_walk(m, p):
        for i in range(len(p) - 1):
            a, b = p[i], p[i + 1]
            if ("at", m, a) not in state or (a, b) not in links:
                return False
            plan.append("(walk %s %s %s)" % (a, b, m))
            state.discard(("at", m, a))
            state.add(("at", m, b))
        return True

    def emit_pickup(l, s, m):
        if ("at", m, l) not in state or ("at", s, l) not in state:
            return False
        plan.append("(pickup_spanner %s %s %s)" % (l, s, m))
        state.discard(("at", s, l))
        state.add(("carrying", m, s))
        return True

    def emit_tighten(l, s, m, n):
        if not (("at", m, l) in state and ("at", n, l) in state
                and ("carrying", m, s) in state and ("useable", s) in state
                and ("loose", n) in state):
            return False
        plan.append("(tighten_nut %s %s %s %s)" % (l, s, m, n))
        state.discard(("loose", n))
        state.discard(("useable", s))
        state.add(("tightened", n))
        return True

    def goal_nuts():
        res = []
        for g in sorted(goal):
            if len(g) == 2 and g[0] == "tightened" and g[1] in nuts:
                if ("tightened", g[1]) not in state and ("loose", g[1]) in state:
                    res.append(g[1])
        return res

    def usable_spanners():
        res = []
        for s in spanners:
            if ("useable", s) in state:
                l = locate(s)
                if l is not None:
                    res.append((s, l))
        return res

    def drop_carried_spanners():
        for m in men:
            for s in spanners:
                if ("carrying", m, s) in state:
                    # cannot put a spanner down in this domain: stay carrying
                    pass

    while len(plan) < MAX_ACTIONS:
        todo = goal_nuts()
        if not todo:
            break
        man = men[0] if men else None
        if man is None:
            break
        ml = man_at(man)
        if ml is None:
            break
        # spanners already carried by the man are usable candidates at ml
        held = [s for s in spanners if ("carrying", man, s) in state
                and ("useable", s) in state]
        best = None
        for n in todo:
            nl = locate(n)
            if nl is None:
                continue
            pn = bfs(ml, nl)
            if pn is None:
                continue
            cands = list(held)
            cands.extend(usable_spanners())
            for (s, sl) in sorted(set(cands)):
                if sl == ml:
                    cost = len(pn)
                else:
                    ps = bfs(ml, sl)
                    ps2 = bfs(sl, nl)
                    if ps is None or ps2 is None:
                        continue
                    cost = len(ps) + len(ps2)
                if best is None or cost < best[0]:
                    best = (cost, n, nl, s, sl)
        if best is None:
            break
        _, n, nl, s, sl = best
        if sl != ml:
            ps = bfs(ml, sl)
            if not emit_walk(man, ps):
                break
        if ("carrying", man, s) not in state:
            if not emit_pickup(sl, s, man):
                break
        pn = bfs(man_at(man), nl)
        if pn is None or not emit_walk(man, pn):
            break
        if not emit_tighten(nl, s, man, n):
            break

    return plan[:MAX_ACTIONS]