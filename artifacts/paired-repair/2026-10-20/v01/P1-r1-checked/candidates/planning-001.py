"""Generic forward-search (BFS) STRIPS planner for the spanner domain.

Reads the same predicates and action schemas exposed by the task. Actions are
grounded lazily from the declared object types, and a breadth-first search
over reachable states finds a plan that reaches a state satisfying all goal
atoms. A parent-pointer map records (state -> (parent_state, action)) so the
plan can be reconstructed in reverse when the goal is reached.
"""

from collections import deque


def get_plan(objects, init, goal):
    # Build object tables by declared type. Each tuple is (name, type).
    by_type = {}
    for name, typ in objects:
        by_type.setdefault(typ, set()).add(name)

    all_locs = by_type.get("location", set())
    all_men = by_type.get("man", set())
    all_nuts = by_type.get("nut", set())
    all_spanners = by_type.get("spanner", set())

    start = frozenset(init)
    goal_set = set(goal)

    def satisfies(state):
        return all(g in state for g in goal_set)

    if satisfies(start):
        return []

    def walk_actions(state):
        out = []
        for m in all_men:
            for l1 in all_locs:
                if ("at", m, l1) not in state:
                    continue
                for l2 in all_locs:
                    if ("link", l1, l2) in state:
                        out.append(("walk", l1, l2, m))
        return out

    def pickup_actions(state):
        out = []
        for m in all_men:
            for l in all_locs:
                if ("at", m, l) not in state:
                    continue
                for s in all_spanners:
                    if ("at", s, l) in state:
                        out.append(("pickup_spanner", l, s, m))
        return out

    def tighten_actions(state):
        out = []
        for m in all_men:
            for l in all_locs:
                if ("at", m, l) not in state:
                    continue
                for n in all_nuts:
                    if ("at", n, l) not in state:
                        continue
                    if ("loose", n) not in state:
                        continue
                    for s in all_spanners:
                        if ("carrying", m, s) in state and ("useable", s) in state:
                            out.append(("tighten_nut", l, s, m, n))
        return out

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
        else:
            raise ValueError("unknown action kind: %r" % (kind,))
        return frozenset(s)

    def fmt(act):
        kind = act[0]
        if kind == "walk":
            return "walk %s %s %s" % (act[1], act[2], act[3])
        if kind == "pickup_spanner":
            return "pickup_spanner %s %s %s" % (act[1], act[2], act[3])
        if kind == "tighten_nut":
            return "tighten_nut %s %s %s %s" % (act[1], act[2], act[3], act[4])
        raise ValueError("unknown action kind: %r" % (kind,))

    MAX_NODES = 500000
    visited = {start}
    parent = {start: None}
    frontier = deque([start])
    expanded = 0

    while frontier:
        state = frontier.popleft()
        expanded += 1
        if expanded > MAX_NODES:
            return []
        succs = []
        for gen in (walk_actions, pickup_actions, tighten_actions):
            for act in gen(state):
                succs.append(act)
        succs.sort(key=lambda a: tuple(str(x) for x in a))
        for act in succs:
            nxt = apply(state, act)
            if nxt in visited:
                continue
            visited.add(nxt)
            parent[nxt] = (state, act)
            if satisfies(nxt):
                # Reconstruct by walking parent pointers backward.
                plan_rev = []
                cur = nxt
                while parent[cur] is not None:
                    prev_state, a = parent[cur]
                    plan_rev.append(fmt(a))
                    cur = prev_state
                plan_rev.reverse()
                if len(plan_rev) > 1000:
                    return []
                return plan_rev
            frontier.append(nxt)
    return []