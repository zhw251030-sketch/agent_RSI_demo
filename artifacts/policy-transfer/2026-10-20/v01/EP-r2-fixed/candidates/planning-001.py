"""Planner for the spanner domain (directed-link semantics).

Key correction over the previous version: `link` is DIRECTED and the reverse
link must never be assumed.  The earlier version built a symmetric adjacency
closure, so the first time the man needed to return towards a spanner it
emitted `(walk gate location4)`, whose precondition `(link gate location4)` is
false.  Execution therefore halted at the first backwards step.

Everything else is unchanged in spirit: each `tighten_nut` consumes the spanner's
`useable` fact, so before every tightening we must be carrying a still useable
spanner.  Movement is a BFS over *directed* link edges only; no location pair is
ever invented.  Every action is emitted only when its full precondition set holds
in the simulated state, so the returned plan is legal even when the goal turns
out to be unreachable (we simply stop early).
"""


def get_plan(objects, init, goal):
    objects = [tuple(o) for o in objects]
    init = [tuple(f) for f in init]
    goal = [tuple(g) for g in goal]

    types = {}
    for name, t in objects:
        types.setdefault(t, set()).add(name)
    men = sorted(types.get("man", set()))
    nuts = sorted(types.get("nut", set()))
    spanners = sorted(types.get("spanner", set()))
    locs = sorted(types.get("location", set()))

    state = set(f for f in init)
    goal_set = set(g for g in goal)

    # ---- directed adjacency: link a b  =>  edge a -> b ONLY ----------------
    adj = dict((l, set()) for l in locs)
    for f in state:
        if len(f) == 3 and f[0] == "link" and f[1] in adj and f[2] in adj:
            adj[f[1]].add(f[2])

    plan = []

    def man_at(m):
        for l in locs:
            if ("at", m, l) in state:
                return l
        return None

    def locate(obj):
        for l in locs:
            if ("at", obj, l) in state:
                return l
        return None

    def path(src, dst):
        """Shortest directed path src -> dst, or None."""
        if src is None or dst is None:
            return None
        if src == dst:
            return [src]
        prev = {src: None}
        frontier = [src]
        while frontier:
            nxt = []
            for u in sorted(frontier):
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
        """Append the directed walk steps, verifying each precondition."""
        for i in range(len(p) - 1):
            a, b = p[i], p[i + 1]
            if ("at", m, a) not in state:
                return False
            if ("link", a, b) not in state:
                return False
            plan.append("(walk %s %s %s)" % (a, b, m))
            state.discard(("at", m, a))
            state.add(("at", m, b))
        return True

    def pending():
        out = []
        for g in sorted(goal_set):
            if len(g) == 2 and g[0] == "tightened" and g[1] in nuts:
                if ("tightened", g[1]) not in state and ("loose", g[1]) in state:
                    out.append(g[1])
        return out

    def usable_spanners():
        out = []
        for s in spanners:
            if ("useable", s) in state and ("at", s, "?") not in []:
                pass
            if ("useable", s) in state:
                sl = locate(s)
                if sl is not None:
                    out.append((s, sl))
        return out

    def try_tighten(n, m, s):
        """Do one fetch+carry+tighten cycle for nut n.  True on success."""
        nl = locate(n)
        if nl is None:
            return False
        cur = man_at(m)
        if cur is None:
            return False
        best = None
        for (sp, sl) in usable_spanners():
            ps = path(cur, sl)
            if ps is None:
                continue
            ps = [cur] + ps if len(ps) == 1 else ps
            p2 = path(sl, nl)
            if p2 is None:
                continue
            if len(p2) == 1:
                p2 = [sl, nl]
            cost = len(ps) + len(p2)
            if best is None or cost < best[0]:
                best = (cost, sp, sl, ps, p2)
        if best is None:
            return False
        _, sp, sl, ps, p2 = best
        if not walk(m, ps):
            return False
        if ("at", sp, sl) not in state or ("at", m, sl) not in state:
            return False
        plan.append("(pickup_spanner %s %s %s)" % (sl, sp, m))
        state.discard(("at", sp, sl))
        state.add(("carrying", m, sp))
        if not walk(m, p2):
            return False
        if man_at(m) != nl:
            return False
        if not (("at", n, nl) in state and ("carrying", m, sp) in state
                and ("useable", sp) in state and ("loose", n) in state):
            return False
        plan.append("(tighten_nut %s %s %s %s)" % (nl, sp, m, n))
        state.discard(("loose", n))
        state.discard(("useable", sp))
        state.discard(("carrying", m, sp))
        state.add(("tightened", n))
        return True

    guard = 0
    while guard < 200:
        guard += 1
        todo = pending()
        if not todo:
            break
        progressed = False
        for n in list(todo):
            if ("tightened", n) in state:
                continue
            for m in men:
                if man_at(m) is None:
                    continue
                if try_tighten(n, m):
                    progressed = True
                    break
            if progressed:
                break
        if not progressed:
            break
        if len(plan) > 990:
            break

    return plan[:1000]