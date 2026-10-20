"""Breadth-first search planner for the STRIPS spanner domain."""

from collections import deque


def _ground_init(objects, init):
    return frozenset(init)


def _apply_walk(state, start, end, man):
    s = set(state)
    s.discard(("at", man, start))
    s.add(("at", man, end))
    return frozenset(s)


def _apply_pickup(state, loc, spanner, man):
    s = set(state)
    s.discard(("at", spanner, loc))
    s.add(("carrying", man, spanner))
    return frozenset(s)


def _apply_tighten(state, loc, spanner, man, nut):
    s = set(state)
    s.discard(("loose", nut))
    s.discard(("useable", spanner))
    s.add(("tightened", nut))
    return frozenset(s)


def get_plan(objects, init, goal):
    mans = sorted(o for o, t in objects if t == "man")
    spanners = sorted(o for o, t in objects if t == "spanner")
    nuts = sorted(o for o, t in objects if t == "nut")
    locations = sorted(o for o, t in objects if t == "location")

    init = frozenset(init)
    goal = frozenset(goal)

    if not goal:
        return []

    for m in mans:
        if all(g in init for g in goal):
            return []

    # Successor generation, ordered deterministically.
    def successors(state):
        out = []
        for m in mans:
            here = None
            for (p, mm, loc) in state:
                if p == "at" and mm == m:
                    here = loc
                    break
            if here is None:
                continue
            for (p, l1, l2) in sorted(state):
                if p == "link" and l1 == here:
                    out.append((_apply_walk(state, here, l2, m),
                                "(walk %s %s %s)" % (here, l2, m)))
            for s in spanners:
                if ("at", s, here) in state:
                    out.append((_apply_pickup(state, here, s, m),
                                "(pickup_spanner %s %s %s)" % (here, s, m)))
            carried = None
            for (p, mm, s) in state:
                if p == "carrying" and mm == m:
                    carried = s
                    break
            if carried is not None and ("useable", carried) in state:
                for n in nuts:
                    if ("at", n, here) in state and ("loose", n) in state:
                        out.append((_apply_tighten(state, here, carried, m, n),
                                    "(tighten_nut %s %s %s %s)" % (here, carried, m, n)))
        return out

    start = init
    if all(g in start for g in goal):
        return []

    seen = {start}
    frontier = deque([(start, [])])
    visited_nodes = 0
    while frontier:
        state, plan = frontier.popleft()
        visited_nodes += 1
        if visited_nodes > 200000:
            return []
        for new_state, action in successors(state):
            if new_state in seen:
                continue
            new_plan = plan + [action]
            if len(new_plan) > 1000:
                continue
            if all(g in new_state for g in goal):
                return new_plan
            seen.add(new_state)
            frontier.append((new_state, new_plan))
    return []