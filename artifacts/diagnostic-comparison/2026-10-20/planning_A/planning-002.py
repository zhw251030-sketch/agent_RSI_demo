"""Greedy/BFS planner for spanner domain - v2."""

from collections import deque


def get_plan(objects, init, goal):
    objects = set(objects)
    init = set(init)
    goal = set(goal)

    men = [n for n, t in objects if t == "man"]
    if not men:
        return []
    man = men[0]

    spanners = sorted(n for n, t in objects if t == "spanner")
    nuts = sorted(n for n, t in objects if t == "nut")

    links = set()
    for fact in init:
        if fact[0] == "link":
            links.add((fact[1], fact[2]))

    # Initial state encoding.
    spanner_locs = {}
    spanner_usable = {}
    nut_locs = {}
    nut_loose = {}
    man_loc = None
    for fact in init:
        if fact[0] == "at":
            _, who, loc = fact
            if who == man:
                man_loc = loc
            elif who in spanner_locs or who in spanners:
                spanner_locs[who] = loc
            elif who in nuts:
                nut_locs[who] = loc
        elif fact[0] == "useable":
            spanner_usable[fact[1]] = True
        elif fact[0] == "loose":
            nut_loose[fact[1]] = True

    def state_key(man_loc, carried, sp_locs, sp_use, nu_loose):
        return (man_loc, carried, tuple(sorted(sp_locs.items())),
                tuple(sorted(sp_use.items())), tuple(sorted(nu_loose.items())))

    def apply(mloc, carried, sp_locs, sp_use, nu_loose, action):
        sp_locs = dict(sp_locs)
        sp_use = dict(sp_use)
        nu_loose = dict(nu_loose)
        carried = carried
        mloc = mloc
        if action[0] == "walk":
            mloc = action[2]
        elif action[0] == "pickup_spanner":
            s = action[2]
            del sp_locs[s]
            carried = s
        elif action[0] == "tighten_nut":
            n = action[4]
            nu_loose[n] = False
            sp_use[carried] = False
            carried = None
        return mloc, carried, sp_locs, sp_use, nu_loose

    def goal_satisfied(nu_loose):
        return all(not nu_loose.get(n, False) for n in nuts)

    initial = state_key(man_loc, None, spanner_locs, spanner_usable, nut_loose)
    if goal_satisfied(nut_loose):
        return []

    # BFS
    visited = {initial}
    queue = deque([((man_loc, None, spanner_locs, spanner_usable, nut_loose), [])])

    while queue:
        (mloc, carried, sp_locs, sp_use, nu_loose), plan = queue.popleft()
        actions = []

        # Walk
        for a, b in links:
            if a == mloc:
                actions.append(("walk", a, b, man))
        # Pickup
        for s in spanners:
            if sp_locs.get(s) == mloc:
                actions.append(("pickup_spanner", mloc, s, man))
        # Tighten
        if carried is not None and sp_use.get(carried, False):
            for n in nuts:
                if nu_loose.get(n, False) and nut_locs.get(n) == mloc:
                    actions.append(("tighten_nut", mloc, carried, man, n))

        for action in actions:
            new_mloc, new_carried, new_sp_locs, new_sp_use, new_nu_loose = apply(
                mloc, carried, sp_locs, sp_use, nu_loose, action
            )
            key = state_key(new_mloc, new_carried, new_sp_locs, new_sp_use, new_nu_loose)
            if key in visited:
                continue
            new_plan = plan + [action]
            if goal_satisfied(new_nu_loose):
                return [_fmt(a) for a in new_plan]
            visited.add(key)
            queue.append(((new_mloc, new_carried, new_sp_locs, new_sp_use, new_nu_loose), new_plan))

    return []


def _fmt(a):
    if a[0] == "walk":
        return f"(walk {a[1]} {a[2]} {a[3]})"
    if a[0] == "pickup_spanner":
        return f"(pickup_spanner {a[1]} {a[2]} {a[3]})"
    if a[0] == "tighten_nut":
        return f"(tighten_nut {a[1]} {a[2]} {a[3]} {a[4]})"
    return str(a)