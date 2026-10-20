"""Greedy round-trip planner for the spanner domain.

Each loose target nut requires a fresh useable spanner (tighten_nut deletes
useable of the spanner).  For every nut we emit: walk to a reachable useable
spanner, pick it up, walk to the nut, tighten.  Walking is planned with BFS
over the directed `link` graph; targets that are not reachable are skipped
instead of aborting the whole plan.
"""


def get_plan(objects, init, goal):
    types = {}
    for pair in objects:
        name, t = pair
        types.setdefault(t, set()).add(name)
    men = sorted(types.get("man", set()))
    nuts = sorted(types.get("nut", set()))
    spanners = sorted(types.get("spanner", set()))
    locs = sorted(types.get("location", set()))

    state = set(tuple(f) for f in init)
    goal = set(tuple(g) for g in goal)

    adj = {l: set() for l in locs}
    for f in state:
        if f[0] == "link" and f[1] in adj and f[2] in adj:
            adj[f[1]].add(f[2])

    def man_loc():
        for m in men:
            for l in locs:
                if ("at", m, l) in state:
                    return (m, l)
        return (None, None)

    def bfs_from(src):
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
        return prev

    def reachable(src, dst):
        if src == dst:
            return [src]
        prev = bfs_from(src)
        if dst not in prev:
            return None
        path = []
        c = dst
        while c is not None:
            path.append(c)
            c = prev[c]
        path.reverse()
        return path

    plan = []

    def do_walk(m, path):
        for i in range(len(path) - 1):
            plan.append("(walk %s %s %s)" % (path[i], path[i + 1], m))
            state.discard(("at", m, path[i]))
            state.add(("at", m, path[i + 1]))

    def locate(obj):
        for l in locs:
            if ("at", obj, l) in state:
                return l
        return None

    def goal_nuts():
        res = []
        for g in sorted(goal):
            if g[0] == "tightened" and g[1] in nuts:
                if ("tightened", g[1]) not in state and ("loose", g[1]) in state:
                    res.append(g[1])
        return res

    def do_pickup(m, l, s):
        plan.append("(pickup_spanner %s %s %s)" % (l, s, m))
        state.discard(("at", s, l))
        state.add(("carrying", m, s))

    def do_tighten(m, l, s, n):
        plan.append("(tighten_nut %s %s %s %s)" % (l, s, m, n))
        state.discard(("loose", n))
        state.discard(("useable", s))
        state.add(("tightened", n))

    # iterate: each pass tightens at least one nut, so the loop terminates
    while True:
        todo = goal_nuts()
        if not todo:
            break
        progressed = False
        for n in todo:
            if ("tightened", n) in state:
                continue
            m, ml = man_loc()
            if m is None:
                break
            nl = locate(n)
            if nl is None:
                continue
            # choose a useable spanner reachable from here
            best = None
            for s in spanners:
                if ("useable", s) not in state:
                    continue
                sl = locate(s)
                if sl is None:
                    continue
                p1 = reachable(ml, sl)
                if p1 is None:
                    continue
                p2 = reachable(sl, nl)
                if p2 is None:
                    continue
                cand = (len(p1) + len(p2), s, sl, p1, p2)
                if best is None or cand[0] < best[0]:
                    best = cand
            if best is None:
                continue
            _, s, sl, p1, p2 = best
            do_walk(m, p1)
            do_pickup(m, sl, s)
            do_walk(m, p2)
            do_tighten(m, nl, s, n)
            progressed = True
            break  # re-evaluate: man location changed
        if not progressed:
            break
        if len(plan) > 1000:
            break

    return plan[:1000]