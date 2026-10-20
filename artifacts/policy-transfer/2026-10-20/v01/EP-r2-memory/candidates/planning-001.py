"""BFS state-space planner for the spanner domain.

Walks are legal only along directed (link ?from ?to) facts, so the
adjacency used by walk actions is the directed link relation, not its
symmetric closure. The greedy one-trip-per-nut strategy in the previous
candidate emitted walk actions that required (link gate location4), but
only (link location4 gate) appears in init; the only consistent plan
that satisfies three nuts at a sink location is to carry all required
spanners to the sink in one trip, which a forward state-space search
finds automatically.
"""


def get_plan(objects, init, goal):
    otypes = {}
    for n, t in objects:
        otypes.setdefault(t, set()).add(n)

    men = sorted(otypes.get("man", set()))
    nuts = sorted(otypes.get("nut", set()))
    spanners = sorted(otypes.get("spanner", set()))
    locs = sorted(otypes.get("location", set()))

    init_f = frozenset(tuple(f) for f in init)
    goal_f = frozenset(tuple(g) for g in goal)

    # directed link adjacency
    out_link = {l: [] for l in locs}
    for f in init_f:
        if f[0] == "link" and f[1] in out_link and f[2] in out_link:
            out_link[f[1]].append(f[2])
    for l in locs:
        out_link[l] = sorted(out_link[l])

    # deterministic action ordering
    def successors(state):
        succs = []
        # walk: for each man at l1, for each link l1->l2, walk
        man_at = {}
        for m in men:
            for l in locs:
                if ("at", m, l) in state:
                    man_at[m] = l
        carrying = {}
        for m in men:
            for s in spanners:
                if ("carrying", m, s) in state:
                    carrying[m] = s
        # walk actions
        for m in men:
            l1 = man_at.get(m)
            if l1 is None:
                continue
            for l2 in out_link[l1]:
                ns = set(state)
                ns.discard(("at", m, l1))
                ns.add(("at", m, l2))
                succs.append((("walk", l1, l2, m), frozenset(ns)))
        # pickup_spanner: man at l, spanner at l, spanner not useable? no,
        # PDDL doesn't require useable for pickup; it lets you pick any.
        for m in men:
            l = man_at.get(m)
            if l is None:
                continue
            for s in spanners:
                if ("at", s, l) in state:
                    ns = set(state)
                    ns.discard(("at", s, l))
                    ns.add(("carrying", m, s))
                    succs.append((("pickup_spanner", l, s, m), frozenset(ns)))
        # tighten_nut: man at l carrying s useable, nut at l loose
        for m in men:
            l = man_at.get(m)
            if l is None:
                continue
            s = carrying.get(m)
            if s is None or ("useable", s) not in state:
                continue
            for n in nuts:
                if ("at", n, l) in state and ("loose", n) in state:
                    ns = set(state)
                    ns.discard(("loose", n))
                    ns.discard(("useable", s))
                    ns.add(("tightened", n))
                    succs.append((("tighten_nut", l, s, m, n), frozenset(ns)))
        return succs

    # BFS
    start = init_f
    parent = {start: (None, None)}
    queue = [start]
    found = None
    # depth limit to keep search bounded; domain instances are small
    depth = {start: 0}
    MAX_DEPTH = 200
    while queue:
        cur = queue.pop(0)
        if goal_f.issubset(cur):
            found = cur
            break
        d = depth[cur]
        if d >= MAX_DEPTH:
            continue
        for action, nxt in successors(cur):
            if nxt not in parent:
                parent[nxt] = (cur, action)
                depth[nxt] = d + 1
                queue.append(nxt)
    if found is None:
        return []

    # reconstruct
    actions = []
    c = found
    while parent[c][0] is not None:
        prev, act = parent[c]
        actions.append(act)
        c = prev
    actions.reverse()

    out = []
    for a in actions:
        out.append("(" + " ".join(a) + ")")
    return out[:1000]
