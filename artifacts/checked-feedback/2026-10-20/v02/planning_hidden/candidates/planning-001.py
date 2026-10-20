"""Generic forward-search (BFS) STRIPS planner for the Spanner-like domain.

The action schemas, preconditions and effects are fixed by the task and are
reproduced here. Actions are grounded lazily using the declared object types,
and a breadth-first search over reachable states finds a plan that reaches a
state satisfying all goal atoms.
"""

from collections import deque


def get_plan(objects, init, goal):
    # Untyped/typed object tables.
    by_type = {}
    for name, typ in objects:
        by_type.setdefault(typ, set()).add(name)

    all_locs = by_type.get("location", set())
    all_men = by_type.get("man", set())
    all_nuts = by_type.get("nut", set())
    all_spanners = by_type.get("spanner", set())

    start = frozenset(init)
    goal = set(goal)

    def is_goal(state):
        return all(g in state for g in goal)

    if is_goal(start):
        return []

    def walk_actions(state):
        acts = []
        for m in all_men:
            for l1 in all_locs:
                if ("at", m, l1) not in state:
                    continue
                for l2 in all_locs:
                    if ("link", l1, l2) in state:
                        acts.append(("walk", l1, l2, m))
        return acts

    def pickup_actions(state):
        acts = []
        for m in all_men:
            for l in all_locs:
                if ("at", m, l) not in state:
                    continue
                for s in all_spanners:
                    if ("at", s, l) in state:
                        acts.append(("pickup_spanner", l, s, m))
        return acts

    def tighten_actions(state):
        acts = []
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
                            acts.append(("tighten_nut", l, s, m, n))
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

    def fmt(act):
        kind = act[0]
        if kind == "walk":
            return "walk %s %s %s" % (act[1], act[2], act[3])
        if kind == "pickup_spanner":
            return "pickup_spanner %s %s %s" % (act[1], act[2], act[3])
        if kind == "tighten_nut":
            return "tighten_nut %s %s %s %s" % (act[1], act[2], act[3], act[4])
        raise ValueError("bad action")

    # Breadth-first search over states with parent pointers for reconstruction.
    # Cap nodes to avoid pathological blowup; these instances are small.
    MAX_NODES = 200000
    start_node = (start, None)
    visited = {start}
    frontier = deque([start_node])
    expanded = 0
    limit = 1000

    while frontier:
        state, _ = frontier.popleft()
        expanded += 1
        if expanded > MAX_NODES:
            return []
        # Successors in a deterministic order (sorted for reproducibility).
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
            node = (nxt, (state, act))
            if is_goal(nxt):
                # reconstruct
                plan = []
                cur = node
                while cur[1] is not None:
                    prev_state, a = cur[1]
                    plan.append(fmt(a))
                    cur = (prev_state, None)
                    # find parent link by scanning is expensive; instead keep pointer
                return plan
            frontier.append(node)
    return []