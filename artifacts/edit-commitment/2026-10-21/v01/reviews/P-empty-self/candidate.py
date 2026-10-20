"""Spanner domain planner - constructive BFS paths with greedy spanner/nut assignment."""

from collections import deque


def _bfs_path(adj, start, goal):
    """Return shortest directed path [start,...,goal] over adj, or None."""
    if start == goal:
        return [start]
    seen = {start: None}
    q = deque([start])
    while q:
        cur = q.popleft()
        for nxt in adj.get(cur, ()):  # deterministic order from sorted init
            if nxt in seen:
                continue
            seen[nxt] = cur
            if nxt == goal:
                path = [nxt]
                while seen[path[-1]] is not None:
                    path.append(seen[path[-1]])
                path.reverse()
                return path
            q.append(nxt)
    return None


def get_plan(objects, init, goal):
    objects = list(objects)
    init = set(init)

    men = sorted(n for n, t in objects if t == "man")
    if not men:
        return []
    man = men[0]

    spanners = sorted(n for n, t in objects if t == "spanner")
    nuts = sorted(n for n, t in objects if t == "nut")

    adj = {}
    at_man = None
    spanner_at = {}
    nut_at = {}
    useable = set()
    loose = set()
    goal_nuts = set()
    for fact in init:
        if not fact:
            continue
        head = fact[0]
        if head == "link":
            adj.setdefault(fact[1], set()).add(fact[2])
        elif head == "at":
            _, who, loc = fact
            if who == man:
                at_man = loc
            elif who in spanners:
                spanner_at[who] = loc
            elif who in nuts:
                nut_at[who] = loc
        elif head == "useable":
            useable.add(fact[1])
        elif head == "loose":
            loose.add(fact[1])

    for g in goal:
        if g and g[0] == "tightened":
            goal_nuts.add(g[1])

    if at_man is None:
        return []

    for s in adj.values():
        pass
    adj = {k: sorted(v) for k, v in adj.items()}

    pending = sorted(n for n in goal_nuts if n in loose and n in nut_at)
    if not pending:
        return []

    plan = []
    man_loc = at_man
    holding = None

    def walk_to(target):
        nonlocal man_loc
        path = _bfs_path(adj, man_loc, target)
        if path is None:
            return False
        for a, b in zip(path, path[1:]):
            plan.append("(walk {0} {1} {2})".format(a, b, man))
        man_loc = target
        return True

    for nut in pending:
        nut_loc = nut_at[nut]
        if not walk_to(nut_loc):
            return []
        if holding is None:
            # Fetch a useable spanner that is still reachable, then return here.
            candidates = [
                s for s in spanners
                if s in spanner_at and s in useable and s not in holding_seen()
            ]
            picked = False
            for s in sorted(candidates):
                s_loc = spanner_at[s]
                save = list(plan)
                if not walk_to(s_loc):
                    plan[:] = save
                    continue
                plan.append("(pickup_spanner {0} {1} {2})".format(s_loc, s, man))
                man_loc = s_loc
                holding = s
                picked = True
                break
            if not picked:
                return []
            if not walk_to(nut_loc):
                return []
        plan.append("(tighten_nut {0} {1} {2} {3})".format(nut_loc, holding, man, nut))
        loose.discard(nut)
        useable.discard(holding)
        spanner_at.pop(holding, None)
        holding = None

    return plan


_USED = set()


def holding_seen():
    return _USED