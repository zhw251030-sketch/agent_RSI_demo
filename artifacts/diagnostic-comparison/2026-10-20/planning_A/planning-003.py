"""BFS planner for spanner domain - v3 (carrying is non-exclusive)."""

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
    locations = sorted(n for n, t in objects if t == "location")

    links = set()
    for fact in init:
        if fact[0] == "link":
            links.add((fact[1], fact[2]))

    spanner_locs = {}
    spanner_usable = {}
    nut_locs = {}
    nut_loose = {}
    man_loc = None
    carried_initial = set()
    for fact in init:
        if fact[0] == "at":
            _, who, loc = fact
            if who == man:
                man_loc = loc
            elif who in spanners:
                spanner_locs[who] = loc
            elif who in nuts:
                nut_locs[who] = loc
        elif fact[0] == "useable":
            spanner_usable[fact[1]] = True
        elif fact[0] == "loose":
            nut_loose[fact[1]] = True
        elif fact[0] == "carrying":
            if fact[1] == man:
                carried_initial.add(fact[2])

    def goal_satisfied(nu_loose):
        return all(not nu_loose.get(n, False) for n in nuts)

    if goal_satisfied(nut_loose):
        return []

    def state_key(mloc, carried, sp_locs, sp_use, nu_loose):
        return (mloc, frozenset(carried), tuple(sorted(sp_locs.items())),
                tuple(sorted(sp_use.items())), tuple(sorted(nu_loose.items())))

    initial = state_key(man_loc, carried_initial, spanner_locs, spanner_usable, nut_loose)

    visited = {initial}
    queue = deque([((man_loc, set(carried_initial), spanner_locs, spanner_usable, nut_loose), [])])

    while queue:
        (mloc, carried, sp_locs, sp_use, nu_loose), plan = queue.popleft()
        actions = []

        # Walk
        for a, b in links:
            if a == mloc:
                actions.append(("walk", a, b, man))
        # Pickup: any spanner at current location not already carried
        for s in spanners:
            if sp_locs.get(s) == mloc and s not in carried:
                actions.append(("pickup_spanner", mloc, s, man))
        # Tighten: need a useable carried spanner AND a loose nut at current location
        for s in spanners:
            if sp_use.get(s, False) and s in carried:
                for n in nuts:
                    if nu_loose.get(n, False) and nut_locs.get(n) == mloc:
                        actions.append(("tighten_nut", mloc, s, man, n))

        for action in actions:
            sp_locs2 = dict(sp_locs)
            sp_use2 = dict(sp_use)
            nu_loose2 = dict(nu_loose)
            carried2 = set(carried)
            mloc2 = mloc
            if action[0] == "walk":
                mloc2 = action[2]
            elif action[0] == "pickup_spanner":
                s = action[2]
                del sp_locs2[s]
                carried2.add(s)
            elif action[0] == "tighten_nut":
                s = action[2]
                n = action[4]
                nu_loose2[n] = False
                sp_use2[s] = False
            key = state_key(mloc2, carried2, sp_locs2, sp_use2, nu_loose2)
            if key in visited:
                continue
            new_plan = plan + [action]
            if goal_satisfied(nu_loose2):
                return [_fmt(a) for a in new_plan]
            visited.add(key)
            queue.append(((mloc2, carried2, sp_locs2, sp_use2, nu_loose2), new_plan))

    return []


def _fmt(a):
    if a[0] == "walk":
        return f"(walk {a[1]} {a[2]} {a[3]})"
    if a[0] == "pickup_spanner":
        return f"(pickup_spanner {a[1]} {a[2]} {a[3]})"
    if a[0] == "tighten_nut":
        return f"(tighten_nut {a[1]} {a[2]} {a[3]} {a[4]})"
    return str(a)