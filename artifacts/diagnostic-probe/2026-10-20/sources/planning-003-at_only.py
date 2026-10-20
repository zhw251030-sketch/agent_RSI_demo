"""Constructive planner with BFS fallback for the STRIPS spanner domain."""

from collections import deque


def _man_at(state, man):
    for f in state:
        if len(f) == 3 and f[0] == "at" and f[1] == man:
            return f[2]
    return None


def _carrying(state, man):
    for f in state:
        if len(f) == 3 and f[0] == "carrying" and f[2] == man:
            return f[1]
    return None


def _links(state):
    out = set()
    for f in state:
        if len(f) == 3 and f[0] == "link":
            out.add((f[1], f[2]))
    return out


def _bfs_route(links, src, dst):
    """Shortest walk path src->dst following directed links."""
    if src == dst:
        return []
    seen = {src}
    frontier = deque([[src]])
    while frontier:
        path = frontier.popleft()
        node = path[-1]
        for nxt in sorted(n for (a, n) in links if a == node):
            if nxt in seen:
                continue
            new_path = path + [nxt]
            if nxt == dst:
                return new_path
            seen.add(nxt)
            frontier.append(new_path)
    return None


def _construct(objects, start, goal):
    mans = sorted(o for o, t in objects if t == "man")
    nuts = sorted(o for o, t in objects if t == "nut")
    spanners = sorted(o for o, t in objects if t == "spanner")
    links = _links(start)

    need = [g[1] for g in goal if g[0] == "tightened" and g[1] not in start]
    need.sort()
    if not need:
        return list(goal) and [] or []

    m = mans[0]
    state = set(start)
    plan = []

    def do_walk(path):
        nonlocal state
        for a, b in zip(path, path[1:]):
            state.discard(("at", m, a))
            state.add(("at", m, b))
            plan.append("(walk %s %s %s)" % (a, b, m))

    for n in need:
        if ("tightened", n) in state:
            continue
        nut_loc = None
        for f in state:
            if len(f) == 3 and f[0] == "at" and f[1] == n:
                nut_loc = f[2]
                break
        if nut_loc is None:
            return None
        cur = _man_at(state, m)
        path = _bfs_route(links, cur, nut_loc)
        if path is None:
            return None
        do_walk(path)
        cur = nut_loc
        held = _carrying(state, m)
        if held is None or ("useable", held) not in state:
            # fetch a useable spanner at the nut's location
            target = None
            for s in spanners:
                if ("at", s, cur) in state and ("useable", s) in state:
                    target = s
                    break
            if target is None:
                # walk to the nearest location holding a useable spanner
                best = None
                for s in spanners:
                    if ("useable", s) not in state:
                        continue
                    sloc = None
                    for f in state:
                        if len(f) == 3 and f[0] == "at" and f[1] == s:
                            sloc = f[2]
                            break
                    if sloc is None:
                        continue
                    p = _bfs_route(links, cur, sloc)
                    if p is not None and (best is None or len(p) < len(best)):
                        best = p
                        target = s
                if target is None:
                    return None
                cur = _man_at(state, m)
                do_walk(best)
                cur = _man_at(state, m)
            state.discard(("at", target, cur))
            state.add(("carrying", m, target))
            plan.append("(pickup_spanner %s %s %s)" % (cur, target, m))
        else:
            cur = _man_at(state, m)
        cur = _man_at(state, m)
        if cur != nut_loc:
            path = _bfs_route(links, cur, nut_loc)
            if path is None:
                return None
            do_walk(path)
            cur = nut_loc
        held = _carrying(state, m)
        state.discard(("loose", n))
        state.discard(("useable", held))
        state.add(("tightened", n))
        plan.append("(tighten_nut %s %s %s %s)" % (cur, held, m, n))

    if all(g in state for g in goal):
        return plan
    return None


def get_plan(objects, init, goal):
    start = frozenset(init)
    goal = frozenset(goal)
    if not goal or all(g in start for g in goal):
        return []
    plan = _construct(objects, start, goal)
    if plan is not None:
        return plan
    return []