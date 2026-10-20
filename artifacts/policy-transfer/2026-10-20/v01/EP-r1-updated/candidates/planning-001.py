"""Planner for the spanner domain.

Rules preserved exactly from the task definition: `link` is DIRECTED, so
movement uses only (link A B) edges in that order.  Each tighten_nut consumes
one `useable` spanner, and a carried spanner stays carried, so the man must
fetch a fresh useable spanner for every loose goal nut that is not co-located
with the man.  We build a full STRIPS simulator, enumerate every ground action
whose typed preconditions hold in the current state, and run breadth-first
search over the resulting state space, choosing the goal-achieving plan of
minimum length.  The state space is small in this domain, so an exhaustive
best-first search is affordable and cannot emit an illegal action.
"""


def get_plan(objects, init, goal):
    types = {}
    for name, t in objects:
        types.setdefault(t, set()).add(name)

    men = sorted(types.get("man", set()))
    nuts = sorted(types.get("nut", set()))
    spanners = sorted(types.get("spanner", set()))
    locs = sorted(types.get("location", set()))
    objects_set = set(objects)

    start = frozenset(tuple(f) for f in init)
    goals = frozenset(tuple(g) for g in goal)

    # directed adjacency, built only from link facts
    adj = dict((l, []) for l in locs)
    for f in start:
        if f[0] == "link" and f[1] in adj and f[2] in adj:
            if f[2] not in adj[f[1]]:
                adj[f[1]].append(f[2])
    for l in adj:
        adj[l].sort()

    def successors(state):
        """Yield (new_state, action_string) for every applicable action."""
        out = []
        # walk: precondition (at m start) and (link start end)
        for m in men:
            for start_l in locs:
                if ("at", m, start_l) not in state:
                    continue
                for end_l in adj[start_l]:
                    ns = set(state)
                    ns.discard(("at", m, start_l))
                    ns.add(("at", m, end_l))
                    out.append((frozenset(ns),
                                "(walk %s %s %s)" % (start_l, end_l, m)))
        # pickup_spanner: (at m l) and (at s l)
        for m in men:
            for l in locs:
                if ("at", m, l) not in state:
                    continue
                for s in spanners:
                    if ("at", s, l) not in state:
                        continue
                    ns = set(state)
                    ns.discard(("at", s, l))
                    ns.add(("carrying", m, s))
                    out.append((frozenset(ns),
                                "(pickup_spanner %s %s %s)" % (l, s, m)))
        # tighten_nut: (at m l) (at n l) (carrying m s) (useable s) (loose n)
        for m in men:
            for l in locs:
                if ("at", m, l) not in state:
                    continue
                held = sorted(s for s in spanners
                              if ("carrying", m, s) in state
                              and ("useable", s) in state)
                if not held:
                    continue
                for n in nuts:
                    if ("at", n, l) not in state or ("loose", n) not in state:
                        continue
                    for s in held:
                        ns = set(state)
                        ns.discard(("loose", n))
                        ns.discard(("useable", s))
                        ns.add(("tightened", n))
                        out.append((frozenset(ns),
                                    "(tighten_nut %s %s %s %s)"
                                    % (l, s, m, n)))
        out.sort(key=lambda p: p[1])
        return out

    def goal_ok(state):
        for g in goals:
            if tuple(g) not in state:
                return False
        return True

    if goal_ok(start):
        return []

    limit = 200000
    # BFS layers keep the shortest plan and bound memory by storing paths only
    # for states actually expanded.
    frontier = [(start, [])]
    seen = set([start])
    expanded = 0
    while frontier and expanded < limit:
        nxt = []
        for (state, path) in frontier:
            if len(path) >= 999:
                continue
            for (ns, act) in successors(state):
                if ns in seen:
                    continue
                np = path + [act]
                if goal_ok(ns):
                    return np
                seen.add(ns)
                nxt.append((ns, np))
            expanded += 1
            if expanded >= limit:
                break
        frontier = nxt

    return []