"""Breadth-first search planner for the STRIPS spanner domain."""

from collections import deque


def _man_location(state, man):
    for f in state:
        if len(f) == 3 and f[0] == "at" and f[1] == man:
            return f[2]
    return None


def _carried_spanner(state, man):
    for f in state:
        if len(f) == 3 and f[0] == "carrying" and f[2] == man:
            return f[1]
    return None


def _links_from(state):
    out = []
    for f in state:
        if len(f) == 3 and f[0] == "link":
            out.append((f[1], f[2]))
    out.sort()
    return out


def get_plan(objects, init, goal):
    mans = sorted(o for o, t in objects if t == "man")
    spanners = sorted(o for o, t in objects if t == "spanner")
    nuts = sorted(o for o, t in objects if t == "nut")

    start = frozenset(init)
    goal = frozenset(goal)

    if not goal or all(g in start for g in goal):
        return []

    links = _links_from(start)

    def successors(state):
        out = []
        for m in mans:
            here = _man_location(state, m)
            if here is None:
                continue
            for (l1, l2) in links:
                if l1 == here:
                    ns = set(state)
                    ns.discard(("at", m, l1))
                    ns.add(("at", m, l2))
                    out.append((frozenset(ns),
                                "(walk %s %s %s)" % (l1, l2, m)))
            for s in spanners:
                if ("at", s, here) in state:
                    ns = set(state)
                    ns.discard(("at", s, here))
                    ns.add(("carrying", m, s))
                    out.append((frozenset(ns),
                                "(pickup_spanner %s %s %s)" % (here, s, m)))
            carried = _carried_spanner(state, m)
            if carried is not None and ("useable", carried) in state:
                for n in nuts:
                    if ("at", n, here) in state and ("loose", n) in state:
                        ns = set(state)
                        ns.discard(("loose", n))
                        ns.discard(("useable", carried))
                        ns.add(("tightened", n))
                        out.append((frozenset(ns),
                                    "(tighten_nut %s %s %s %s)" % (here, carried, m, n)))
        return out

    seen = {start}
    frontier = deque([(start, [])])
    nodes = 0
    while frontier:
        state, plan = frontier.popleft()
        nodes += 1
        if nodes > 300000:
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