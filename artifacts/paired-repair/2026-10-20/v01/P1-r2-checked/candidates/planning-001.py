"""Breadth-first STRIPS planner for the Spanner domain.

Takes objects/init/goal as sets of tuples and returns a list of grounded
action strings. Actions are enumerated lazily from the state and states are
visited in a deterministic (sorted) order, so results are reproducible
regardless of set iteration order. Nodes are cached with parent pointers for
exact plan reconstruction.
"""

from collections import deque


def get_plan(objects, init, goal):
    by_type = {}
    for name, typ in objects:
        by_type.setdefault(typ, set()).add(name)

    locs = sorted(by_type.get("location", set()))
    men = sorted(by_type.get("man", set()))
    nuts = sorted(by_type.get("nut", set()))
    spanners = sorted(by_type.get("spanner", set()))

    start = frozenset(init)
    goal_set = frozenset(goal)

    def is_goal(state):
        return goal_set.issubset(state)

    if is_goal(start):
        return []

    def successors(state):
        acts = []
        for m in men:
            here = None
            for l in locs:
                if ("at", m, l) in state:
                    here = l
                    break
            if here is None:
                continue
            for l2 in locs:
                if ("link", here, l2) in state:
                    acts.append(("walk", here, l2, m))
            for s in spanners:
                if ("at", s, here) in state:
                    acts.append(("pickup_spanner", here, s, m))
            if any(("carrying", m, s) in state and ("useable", s) in state
                   for s in spanners):
                for n in nuts:
                    if ("loose", n) in state and ("at", n, here) in state:
                        for s in spanners:
                            if ("carrying", m, s) in state and ("useable", s) in state:
                                acts.append(("tighten_nut", here, s, m, n))
        return acts

    def apply(state, act):
        s = set(state)
        kind = act[0]
        if kind == "walk":
            s.discard(("at", act[3], act[1]))
            s.add(("at", act[3], act[2]))
        elif kind == "pickup_spanner":
            s.discard(("at", act[2], act[1]))
            s.add(("carrying", act[3], act[2]))
        elif kind == "tighten_nut":
            s.discard(("loose", act[4]))
            s.discard(("useable", act[2]))
            s.add(("tightened", act[4]))
        return frozenset(s)

    def fmt(act):
        return "%s %s %s %s" % act if len(act) == 4 else "%s %s %s %s %s" % act

    MAX_NODES = 300000
    visited = {start}
    parent = {start: None}
    frontier = deque([start])
    expanded = 0

    while frontier:
        state = frontier.popleft()
        expanded += 1
        if expanded > MAX_NODES:
            return []
        for act in successors(state):
            nxt = apply(state, act)
            if nxt in visited:
                continue
            visited.add(nxt)
            parent[nxt] = (state, act)
            if is_goal(nxt):
                plan = []
                cur = nxt
                while parent[cur] is not None:
                    prev_state, a = parent[cur]
                    plan.append(fmt(a))
                    cur = prev_state
                plan.reverse()
                return plan[:1000]
            frontier.append(nxt)
    return []