"""Greedy sequential planner for the spanner domain."""


def get_plan(objects, init, goal):
    # Build type index
    types = {}
    for name, t in objects:
        types.setdefault(t, set()).add(name)
    men = sorted(types.get("man", set()))
    nuts = sorted(types.get("nut", set()))
    spanners = sorted(types.get("spanner", set()))
    locs = sorted(types.get("location", set()))

    state = set(tuple(f) for f in init)
    goal = set(tuple(g) for g in goal)
    plan = []

    def add(a):
        plan.append(a)

    def at_man():
        for l in locs:
            if ("at", men[0], l) in state:
                return l
        return None

    def walk_to(target):
        cur = at_man()
        if cur == target:
            return True
        # BFS over directed links
        prev = {cur: None}
        q = [cur]
        found = False
        while q:
            nq = []
            for u in q:
                for v in locs:
                    if ("link", u, v) in state and v not in prev:
                        prev[v] = u
                        if v == target:
                            found = True
                        nq.append(v)
            q = nq
        if not found and target not in prev:
            return False
        path = []
        c = target
        while c is not None:
            path.append(c)
            c = prev[c]
        path.reverse()
        for i in range(len(path) - 1):
            add("(walk %s %s %s)" % (path[i], path[i + 1], men[0]))
            state.discard(("at", men[0], path[i]))
            state.add(("at", men[0], path[i + 1]))
        return True

    def nut_loc(n):
        for l in locs:
            if ("at", n, l) in state:
                return l
        return None

    def pick_up_s():
        cur = at_man()
        here = [s for s in spanners if ("at", s, cur) in state]
        return here[0] if here else None

    remaining = [n for n in nuts if ("tightened", n) in goal and ("tightened", n) not in state]
    remaining.sort()
    carried = pick_up_s()

    for n in remaining:
        if ("tightened", n) not in goal:
            continue
        nl = nut_loc(n)
        if nl is None:
            continue
        if carried is None or ("useable", carried) not in state:
            # find a useable spanner somewhere and fetch it
            found = None
            for s in spanners:
                if ("useable", s) not in state:
                    continue
                if ("at", s, at_man()) in state:
                    found = s
                    break
                for l in locs:
                    if ("at", s, l) in state:
                        if walk_to(l):
                            found = s
                            break
                if found:
                    break
            if found is None:
                break
            add("(pickup_spanner %s %s %s)" % (at_man(), found, men[0]))
            state.discard(("at", found, at_man()))
            state.add(("carrying", men[0], found))
            carried = found
        walk_to(nl)
        add("(tighten_nut %s %s %s %s)" % (nl, carried, men[0], n))
        state.discard(("loose", n))
        state.discard(("useable", carried))
        state.add(("tightened", n))
        carried = None

    # re-check goals
    if all(tuple(g) in state for g in goal):
        return plan[:1000]
    return plan[:1000]