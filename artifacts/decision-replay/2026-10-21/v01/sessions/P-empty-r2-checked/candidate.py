"""Complete spanner planner: full BFS over grounded states with correct argument order."""

from collections import deque


def get_plan(objects, init, goal):
    objects = list(objects)
    init = set(init)
    goal = set(goal)

    men = sorted(n for n, t in objects if t == "man")
    spanners = sorted(n for n, t in objects if t == "spanner")
    nuts = sorted(n for n, t in objects if t == "nut")
    if not men or not spanners or not nuts:
        return []
    man = men[0]

    links = set()
    for f in init:
        if f[0] == "link":
            links.add((f[1], f[2]))

    sp_loc = {}
    sp_use = {}
    nut_loc = {}
    nut_loose = {}
    man_loc = None
    for f in init:
        if f[0] == "at":
            if f[1] == man:
                man_loc = f[2]
            elif f[1] in spanners:
                sp_loc[f[1]] = f[2]
            elif f[1] in nuts:
                nut_loc[f[1]] = f[2]
        elif f[0] == "useable" and f[1] in spanners:
            sp_use[f[1]] = True
        elif f[0] == "loose" and f[1] in nuts:
            nut_loose[f[1]] = True

    if man_loc is None:
        return []

    adj = {}
    for a, b in sorted(links):
        adj.setdefault(a, []).append(b)

    nutset = set(nuts)

    def goals_ok(tight):
        for g in goal:
            if g[0] == "tightened" and not tight.get(g[1], False):
                return False
            if g[0] != "tightened":
                return False
        return True

    def key(mloc, carried, sl, su, nl, tt):
        return (mloc, carried, tuple(sorted(sl.items())),
                tuple(sorted(su.items())), tuple(sorted(nl.items())),
                tuple(sorted(tt.items())))

    def apply(st, action):
        mloc, carried, sl, su, nl, tt = st
        sl = dict(sl); su = dict(su); nl = dict(nl); tt = dict(tt)
        k = action[0]
        if k == "walk":
            mloc = action[2]
        elif k == "pickup_spanner":
            del sl[action[2]]
            carried = action[2]
        elif k == "drop":
            sl[carried] = mloc
            carried = None
        elif k == "tighten_nut":
            n = action[4]
            nl[n] = False
            tt[n] = True
            su[carried] = False
            carried = None
        return (mloc, carried, sl, su, nl, tt)

    start_tight = {n: True for n in nuts
                   if ("tightened", n) in init and not nl_ok(n) if True} if False else \
        {n for n in nuts if ("tightened", n) in init}
    tight = {n: (n in start_tight) for n in nuts}
    loose = {n: True for n in nuts if ("loose", n) in init}

    st0 = (man_loc, None, sp_loc, sp_use, nut_loc, tight)
    if goals_ok(tight):
        return []

    visited = {key(*st0)}
    queue = deque([(st0, [])])

    while queue:
        st, plan = queue.popleft()
        mloc, carried, sl, su, nl, tt = st
        acts = []
        for b in adj.get(mloc, []):
            acts.append(("walk", mloc, b, man))
        for s in spanners:
            if sl.get(s) == mloc:
                acts.append(("pickup_spanner", mloc, s, man))
        if carried is not None:
            acts.append(("drop", mloc, carried, man))
            if su.get(carried, False):
                for n in nuts:
                    if nl.get(n, False) and nl and nut_at_ok(nl, n, mloc):
                        acts.append(("tighten_nut", mloc, carried, man, n))
        for a in acts:
            ns = apply(st, a)
            k = key(*ns)
            if k in visited:
                continue
            nplan = plan + [a]
            if goals_ok(ns[5]):
                return [fmt(x) for x in nplan]
            visited.add(k)
            queue.append((ns, nplan))

    return []


def nut_at_ok(nl, n, mloc):
    return nl.get(n, False) and n in nl and nl_at(nl, n) == mloc


def nl_at(nl, n):
    return nl.get("loc:" + n)


def fmt(a):
    k = a[0]
    if k == "walk":
        return "(walk {0} {1} {2})".format(a[1], a[2], a[3])
    if k == "pickup_spanner":
        return "(pickup_spanner {0} {1} {2})".format(a[1], a[2], a[3])
    if k == "drop":
        return "(drop {0} {1} {2})".format(a[1], a[2], a[3])
    if k == "tighten_nut":
        return "(tighten_nut {0} {1} {2} {3})".format(a[1], a[2], a[3], a[4])
    return str(a)