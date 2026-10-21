"""Grounded planner for the 'spanner' planning domain.

Public contract:
    get_plan(objects, init, goal) -> list[str]

`objects` is a collection of (name, type) pairs; `init` and `goal` are
collections of predicate tuples (given as arrays in JSON).  The returned plan
is a list of parenthesized grounded action strings, using exactly the argument
order given in the domain definition.
"""

import collections

MAX_STEPS = 1000


def _fmt(action, args):
    return "(" + " " + " ".join([action] + [str(a) for a in args]) + ")"


def get_plan(objects, init, goal):
    # ------------------------------------------------------------------
    # Static, typed world model.  Inputs are never mutated.
    # ------------------------------------------------------------------
    types = {}
    for pair in objects:
        name, tname = pair[0], pair[1]
        types.setdefault(name, set()).add(tname)

    def isa(obj, tname):
        return tname in types.get(obj, ())

    state = set()
    for fact in init:
        state.add(tuple(fact))

    goal_facts = set(tuple(g) for g in goal)

    links = collections.defaultdict(set)
    for f in list(state):
        if f[0] == "link":
            links[f[1]].add(f[2])

    locations = sorted(n for n in types if isa(n, "location"))
    nuts = sorted(n for n in types if isa(n, "nut"))
    spanners = sorted(n for n in types if isa(n, "spanner"))
    men = sorted(n for n in types if isa(n, "man"))

    def loc_of(x):
        for f in state:
            if f[0] == "at" and f[1] == x and isa(f[2], "location"):
                return f[2]
        return None

    # ------------------------------------------------------------------
    # Grounded action appliers with full precondition checks.
    # ------------------------------------------------------------------
    def apply_walk(s, e, m):
        if ("at", m, s) in state and ("link", s, e) in state:
            state.discard(("at", m, s))
            state.add(("at", m, e))
            return _fmt("walk", (s, e, m))
        return None

    def apply_pickup(l, s, m):
        if ("at", m, l) in state and ("at", s, l) in state:
            state.discard(("at", s, l))
            state.add(("carrying", m, s))
            return _fmt("pickup_spanner", (l, s, m))
        return None

    def apply_tighten(l, s, m, n):
        if (("at", m, l) in state and ("at", n, l) in state
                and ("carrying", m, s) in state
                and ("useable", s) in state and ("loose", n) in state):
            state.discard(("loose", n))
            state.discard(("useable", s))
            state.add(("tightened", n))
            return _fmt("tighten_nut", (l, s, m, n))
        return None

    def bfs_path(src, dst):
        if src == dst:
            return []
        seen = {src}
        queue = collections.deque([[src]])
        while queue:
            p = queue.popleft()
            last = p[-1]
            for nxt in sorted(links.get(last, ())):
                if nxt in seen:
                    continue
                np = p + [nxt]
                if nxt == dst:
                    return np
                seen.add(nxt)
                queue.append(np)
        return None

    # ------------------------------------------------------------------
    # Candidate grounded actions (always sorted for determinism).
    # ------------------------------------------------------------------
    def successors():
        out = []
        for m in men:
            here = None
            for f in state:
                if f[0] == "at" and f[1] == m and isa(f[2], "location"):
                    here = f[2]
                    break
            if here is None:
                continue
            for nxt in sorted(links.get(here, ())):
                out.append((m, here, nxt))
            for s in spanners:
                if ("at", s, here) in state:
                    out.append((m, here, s))
        return out

    def act(a):
        m = a[0]
        if a[3] is None or len(a) == 4 and False:
            return None
        if len(a) == 3 and a[2] in links.get(a[1], ()):
            return apply_walk(a[1], a[2], m)
        for s in spanners:
            if s == a[2]:
                return apply_pickup(a[1], a[2], m)
        return None

    def apply_walk_pick(m, a, b):
        if ("at", m, a) in state and ("link", a, b) in state:
            state.discard(("at", m, a))
            state.add(("at", m, b))
            return _fmt("walk", (a, b, m))
        if ("at", m, a) in state:
            for s in spanners:
                if s == b and ("at", s, a) in state:
                    state.discard(("at", s, a))
                    state.add(("carrying", m, s))
                    return _fmt("pickup_spanner", (a, s, m))
        return None

    def apply(m, a, b):
        return apply_walk_pick(m, a, b)

    def goal_satisfied():
        return all(f in state for f in goal_facts)

    # ------------------------------------------------------------------
    # Deterministic greedy search with best-first pruning, then fallback
    # breadth-first style DFS with a step budget.
    # ------------------------------------------------------------------
    plan = []
    budget = [MAX_STEPS]

    def snapshot():
        return set(state)

    def restore(snap, plen):
        state.clear()
        state.update(snap)
        del plan[plen:]

    def goal_nuts_remaining():
        rem = []
        for n in nuts:
            if ("tightened", n) in goal_facts and ("loose", n) in state:
                rem.append(n)
        return rem

    # BFS path helper that walks the man to a destination, applying actions.
    def move_to(m, dst, rec):
        start = loc_of(m)
        if start is None or start == dst:
            return True
        p = bfs_path(start, dst)
        if p is None:
            return False
        for i in range(len(p) - 1):
            if len(rec) + 1 > budget[0]:
                return False
            a = apply_walk(p[i], p[i + 1], m)
            if a is None:
                return False
            rec.append(a)
        return True

    def solve_for_man(m):
        rec = []
        snap = snapshot()
        base = len(rec)

        def undo():
            restore(snap, 0)

        # Strategy: for each pending nut, if we hold no useable spanner,
        # fetch the cheapest reachable useable spanner, then tighten.
        guard = [0]
        while True:
            guard[0] += 1
            if guard[0] > 4 * (len(nuts) + 1) * (len(spanners) + 1) + 16:
                undo()
                return None
            rem = goal_nuts_remaining()
            if not rem:
                out = list(rec)
                undo()
                return out
            progressed = False
            for n in rem:
                nl = loc_of(n)
                if nl is None:
                    continue
                if not move_to(m, nl, rec):
                    continue
                holding = None
                for f in sorted(state):
                    if f[0] == "carrying" and f[1] == m and f[2] in spanners:
                        holding = f[2]
                if holding is None or ("useable", holding) not in state:
                    got = False
                    for s in spanners:
                        if ("useable", s) not in state:
                            continue
                        sl = loc_of(s)
                        if sl is None:
                            continue
                        if not move_to(m, sl, rec):
                            continue
                        if not move_to(m, nl, rec):
                            continue
                        a = apply_pickup(sl, s, m)
                        if a is None:
                            continue
                        rec.append(a)
                        holding = s
                        got = True
                        break
                    if not got:
                        continue
                else:
                    if not move_to(m, nl, rec):
                        continue
                a = apply_tighten(nl, holding, m, n)
                if a is None:
                    continue
                rec.append(a)
                progressed = True
                break
            if not progressed:
                undo()
                return None

    for m in men:
        res = solve_for_man(m)
        if res is not None and len(res) <= budget[0]:
            plan = res
            break

    # ------------------------------------------------------------------
    # Fallback: uniform-cost style DFS over grounded walk/pickup/tighten.
    # ------------------------------------------------------------------
    if not plan:
        def dfs(man, rec, snap, depth):
            if all(f in state for f in goal_facts):
                return list(rec)
            if depth > 60 or len(rec) > budget[0]:
                return None
            cands = []
            for m2 in men:
                here = loc_of(m2)
                if here is None:
                    continue
                for nxt in sorted(links.get(here, ())):
                    cands.append((m2, "walk", (here, nxt, m2)))
                for s in spanners:
                    if ("at", s, here) in state:
                        cands.append((m2, "pickup", (here, s, m2)))
                for s in spanners:
                    if ("carrying", m2, s) in state and ("useable", s) in state:
                        for n in nuts:
                            if ("at", n, here) in state and ("loose", n) in state:
                                cands.append((m2, "tighten", (here, s, m2, n)))
            for m2, kind, args in cands:
                before = snapshot()
                if kind == "walk":
                    a = apply_walk(args[0], args[1], args[2])
                elif kind == "pickup":
                    a = apply_pickup(args[0], args[1], args[2])
                else:
                    a = apply_tighten(args[0], args[1], args[2], args[3])
                if a is None:
                    restore(before, len(rec))
                    continue
                rec.append(a)
                got = dfs(m2, rec, before, depth + 1)
                if got is not None:
                    return got
                restore(before, len(rec))
            return None

        got = dfs(men[0] if men else None, [], set(state), 0)
        if got is not None:
            plan = got

    if len(plan) > MAX_STEPS:
        return []
    return list(plan)