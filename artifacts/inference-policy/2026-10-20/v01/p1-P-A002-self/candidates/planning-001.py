"""Spanner domain planner - BFS over grounded states, returns list[str]."""

from collections import deque


def get_plan(objects, init, goal):
    objects = set(objects)
    init = set(init)
    goal = set(goal)

    men = sorted(n for n, t in objects if t == "man")
    if not men:
        return []
    man = men[0]

    spanners = sorted(n for n, t in objects if t == "spanner")
    nuts = sorted(n for n, t in objects if t == "nut")
    locations = sorted(n for n, t in objects if t == "location")

    spanner_set = set(spanners)
    nut_set = set(nuts)

    links = set()
    man_loc = None
    sp_locs = {}
    sp_use = {}
    nut_locs = {}
    nut_loose = {}

    for fact in init:
        if not fact:
            continue
        p = fact[0]
        if p == "link":
            links.add((fact[1], fact[2]))
        elif p == "at":
            _, who, loc = fact
            if who == man:
                man_loc = loc
            elif who in spanner_set:
                sp_locs[who] = loc
            elif who in nut_set:
                nut_locs[who] = loc
        elif p == "useable":
            sp_use[fact[1]] = True
        elif p == "loose":
            nut_loose[fact[1]] = True

    goal_tight = set(f[1] for f in goal if f and f[0] == "tightened")
    if not goal_tight:
        goal_tight = set(nuts)

    def satisfied(nl):
        return all(not nl.get(n, False) for n in goal_tight)

    def key(mloc, carried, sl, su, nl):
        return (mloc, carried,
                tuple(sorted(sl.items())),
                tuple(sorted(su.items())),
                tuple(sorted(nl.items())))

    start = (man_loc, None, sp_locs, sp_use, nut_loose)
    if satisfied(nut_loose):
        return []

    out_links = {}
    for a, b in links:
        out_links.setdefault(a, set()).add(b)

    visited = {key(*start)}
    queue = deque([(start, [])])

    while queue:
        (mloc, carried, sl, su, nl), plan = queue.popleft()

        actions = []
        for b in sorted(out_links.get(mloc, ())):
            actions.append(("walk", mloc, b, man))
        for s in spanners:
            if sl.get(s) == mloc:
                actions.append(("pickup_spanner", mloc, s, man))
        if carried is not None and su.get(carried, False):
            for n in nuts:
                if nl.get(n, False) and nut_locs.get(n) == mloc:
                    actions.append(("tighten_nut", mloc, carried, man, n))

        for action in actions:
            new_mloc, new_carried, new_sl, new_su, new_nl = mloc, carried, sl, su, nl
            if action[0] == "walk":
                new_mloc = action[2]
            elif action[0] == "pickup_spanner":
                s = action[2]
                new_sl = dict(sl)
                new_sl.pop(s, None)
                new_carried = s
            else:
                n = action[4]
                new_nl = dict(nl)
                new_nl[n] = False
                new_su = dict(su)
                new_su[carried] = False
            k = key(new_mloc, new_carried, new_sl, new_su, new_nl)
            if k in visited:
                continue
            new_plan = plan + [action]
            if satisfied(new_nl):
                return [fmt(a) for a in new_plan]
            visited.add(k)
            queue.append(((new_mloc, new_carried, new_sl, new_su, new_nl), new_plan))

    return []


def fmt(a):
    return "(" + " ".join([a[0]] + list(a[1:])) + ")"