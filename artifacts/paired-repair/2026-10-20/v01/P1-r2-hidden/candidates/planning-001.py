"""Generic forward-search (BFS) STRIPS planner for the Spanner-like domain.

Returns parenthesized action strings, e.g. "(walk location1 location2 bob)".
"""

from collections import deque


def _by_type(objects):
    table = {}
    for item in objects:
        name, typ = item[0], item[1]
        table.setdefault(typ, set()).add(name)
    return table


def _fmt(act):
    kind = act[0]
    if kind == "walk":
        return "(walk %s %s %s)" % (act[1], act[2], act[3])
    if kind == "pickup_spanner":
        return "(pickup_spanner %s %s %s)" % (act[1], act[2], act[3])
    if kind == "tighten_nut":
        return "(tighten_nut %s %s %s %s)" % (act[1], act[2], act[3], act[4])
    raise ValueError("unknown action kind: %r" % (kind,))


def get_plan(objects, init, goal):
    types = _by_type(list(objects))
    locs = sorted(types.get("location", ()))
    men = sorted(types.get("man", ()))
    nuts = sorted(types.get("nut", ()))
    spanners = sorted(types.get("spanner", ()))

    start = frozenset(init)
    goals = set(goal)

    def satisfied(state):
        return all(g in state for g in goals)

    if satisfied(start) or not goals:
        return []

    def successors(state):
        acts = []
        # walk
        for m in men:
            here = [l for l in locs if ("at", m, l) in state]
            for l1 in here:
                for l2 in locs:
                    if ("link", l1, l2) in state:
                        acts.append(("walk", l1, l2, m))
            # pickup_spanner
            for l1 in here:
                for s in spanners:
                    if ("at", s, l1) in state:
                        acts.append(("pickup_spanner", l1, s, m))
            # tighten_nut
            for l1 in here:
                here_nuts = [n for n in nuts
                             if ("at", n, l1) in state and ("loose", n) in state]
                if not here_nuts:
                    continue
                held = [s for s in spanners
                        if ("carrying", m, s) in state and ("useable", s) in state]
                for n in here_nuts:
                    for s in held:
                        acts.append(("tighten_nut", l1, s, m, n))
        acts.sort(key=lambda a: tuple(str(x) for x in a))
        return acts

    def apply(state, act):
        s = set(state)
        kind = act[0]
        if kind == "walk":
            _, l1, l2, m = act
            s.discard(("at", m, l1))
            s.add(("at", m, l2))
        elif kind == "pickup_spanner":
            _, l, sp, m = act
            s.discard(("at", sp, l))
            s.add(("carrying", m, sp))
        elif kind == "tighten_nut":
            _, l, sp, m, n = act
            s.discard(("loose", n))
            s.discard(("useable", sp))
            s.add(("tightened", n))
        return frozenset(s)

    max_expansions = 300000
    visited = set([start])
    parents = {start: None}
    frontier = deque([start])
    expansions = 0

    while frontier:
        state = frontier.popleft()
        expansions += 1
        if expansions > max_expansions:
            return []
        for act in successors(state):
            nxt = apply(state, act)
            if nxt in visited:
                continue
            visited.add(nxt)
            parents[nxt] = (state, act)
            if satisfied(nxt):
                plan = []
                cur = nxt
                while parents[cur] is not None:
                    prev, a = parents[cur]
                    plan.append(_fmt(a))
                    cur = prev
                plan.reverse()
                if len(plan) <= 1000:
                    return plan
                return []
            frontier.append(nxt)
    return []