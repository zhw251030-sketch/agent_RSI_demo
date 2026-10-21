"""Grounded planner for the 'spanner' planning domain.

Public contract:
    get_plan(objects, init, goal) -> list[str]

`objects` is a collection of (name, type) pairs; `init` and `goal` are
collections of predicate tuples (given as arrays in JSON).  The returned plan
is a list of parenthesized grounded action strings, using exactly the argument
order given in the domain definition.
"""

import collections


def _fmt(action, args):
    return "(" + " " + " ".join([action] + list(args)) + ")"


def get_plan(objects, init, goal):
    # ------------------------------------------------------------------
    # Build the static, typed world model from the inputs (no mutation).
    # ------------------------------------------------------------------
    types = {}
    for pair in objects:
        name, tname = pair[0], pair[1]
        types.setdefault(name, set()).add(tname)

    def isa(obj, tname):
        return tname in types.get(obj, ())

    state = set()
    for fact in init:
        state.add(tuple(fact))

    def holds(fact):
        return fact in state

    def apply_add(adds):
        for f in adds:
            state.add(tuple(f))

    def apply_del(dels):
        for f in dels:
            state.discard(tuple(f))

    # ------------------------------------------------------------------
    # Static structure: link graph over locations, plus typed indexes.
    # ------------------------------------------------------------------
    links = collections.defaultdict(set)
    for fact in list(state):
        if fact[0] == "link":
            links[fact[1]].add(fact[2])

    locations = sorted(n for n in types if isa(n, "location"))
    nuts = sorted(n for n in types if isa(n, "nut"))
    spanners = sorted(n for n in types if isa(n, "spanner"))
    men = sorted(n for n in types if isa(n, "man"))

    goal_facts = set(tuple(g) for g in goal)

    plan = []

    # ------------------------------------------------------------------
    # Grounded action appliers.  Each takes explicit arguments, checks
    # preconditions against the current state, applies effects and appends
    # the corresponding grounded string.
    # ------------------------------------------------------------------
    def do_walk(start, end, m):
        if holds(("at", m, start)) and holds(("link", start, end)):
            apply_del([("at", m, start)])
            apply_add([("at", m, end)])
            plan.append(_fmt("walk", (start, end, m)))
            return True
        return False

    def do_pickup(l, s, m):
        if holds(("at", m, l)) and holds(("at", s, l)):
            apply_del([("at", s, l)])
            apply_add([("carrying", m, s)])
            plan.append(_fmt("pickup_spanner", (l, s, m)))
            return True
        return False

    def do_tighten(l, s, m, n):
        if (holds(("at", m, l)) and holds(("at", n, l))
                and holds(("carrying", m, s)) and holds(("useable", s))
                and holds(("loose", n))):
            apply_del([("loose", n), ("useable", s)])
            apply_add([("tightened", n)])
            plan.append(_fmt("tighten_nut", (l, s, m, n)))
            return True
        return False

    # ------------------------------------------------------------------
    # Helpers built on the grounded actions above.
    # ------------------------------------------------------------------
    def man_at(m):
        for f in state:
            if f[0] == "at" and f[1] == m and isa(f[2], "location"):
                return f[2]
        return None

    def nut_at(n):
        for f in state:
            if f[0] == "at" and f[1] == n and isa(f[2], "location"):
                return f[2]
        return None

    def spanner_at(s):
        for f in state:
            if f[0] == "at" and f[1] == s and isa(f[2], "location"):
                return f[2]
        return None

    def carried_spanners(m):
        out = []
        for f in state:
            if f[0] == "carrying" and f[1] == m:
                out.append(f[2])
        return out

    def all_man_locations(m):
        s = set()
        for f in state:
            if f[0] == "at" and f[1] == m and isa(f[2], "location"):
                s.add(f[2])
        return s

    def path(src, dst):
        """Breadth-first shortest route over the directed link graph."""
        if src == dst:
            return []
        seen = {src}
        queue = collections.deque([[src]])
        while queue:
            p = queue.popleft()
            last = p[-1]
            for nxt in sorted(links.get(last, ())):
                if nxt in seen:
                    continue
                np = p + [nxt]
                if nxt == dst:
                    return np
                seen.add(nxt)
                queue.append(np)
        return None

    def goto(m, dst):
        """Move man m to dst, walking along a shortest link path."""
        while True:
            here = man_at(m)
            if here is None:
                return False
            if here == dst:
                return True
            p = path(here, dst)
            if p is None:
                return False
            if len(plan) + 2 > 1000:
                return False
            for i in range(len(p) - 1):
                if not do_walk(p[i], p[i + 1], m):
                    return False

    # ------------------------------------------------------------------
    # Search for a short applicable plan over the relevant choices.
    # ------------------------------------------------------------------
    relevant_locs = set(locations)
    for f in list(state):
        if f[0] == "at" and isa(f[2], "location"):
            relevant_locs.add(f[2])
    for n in nuts:
        nl = nut_at(n)
        if nl is not None:
            relevant_locs.add(nl)
    for s in spanners:
        sl = spanner_at(s)
        if sl is not None:
            relevant_locs.add(sl)

    start_nuts = tuple(nuts)
    start_spanners = tuple(spanners)
    start_men = tuple(men)

    def relaxed_reachable_man_loc(m, targets, max_walk):
        """Reachable location set for m ignoring carrying constraints."""
        reach = set(all_man_locations(m))
        frontier = set(reach)
        steps = 0
        while frontier and steps < max_walk:
            nxt = set()
            for l in frontier:
                nxt |= links.get(l, set())
            nxt -= reach
            nxt &= set(relevant_locs) | targets
            reach |= nxt
            frontier = nxt
            steps += 1
        return reach

    def search():
        """Enumerate candidate plans, return the first that fully applies."""
        goal_nuts = set(n for n in start_nuts
                        if ("tightened", n) in goal_facts)

        # order nuts: already-tightened first (to skip), then others
        pending = [n for n in start_nuts
                   if ("loose", n) in state and n in goal_nuts]
        # leave non-goal nuts alone
        pending.sort(key=lambda n: (nut_at(n) is None, nut_at(n) or "",
                                    n))

        for man in start_men:
            for spanner in start_spanners:
                for nut_list in _nut_orders(pending):
                    for fixed in _bool_orders(len(nut_list)):
                        trial = []
                        ok = True
                        cur = man
                        holding = None
                        for nut, keep in zip(nut_list, fixed):
                            nl = nut_at(nut)
                            if nl is None:
                                ok = False
                                break
                            if not _goto(trial, cur, nl):
                                ok = False
                                break
                            if holding is None:
                                if not _ensure_spn(trial, cur, spanner,
                                                   nl, keep):
                                    ok = False
                                    break
                                holding = spanner
                            if not _tight(trial, cur, holding, nut):
                                ok = False
                                break
                            if keep:
                                holding = None
                        if ok:
                            return trial
        return None

    def _nut_orders(pending):
        yield list(pending)

    def _bool_orders(k):
        # first try keeping every spanner, then drop progressively
        for keep_first in range(k, -1, -1):
            yield [i < keep_first for i in range(k)]

    def _goto(trial, m, dst):
        """Append walk actions moving m to dst onto trial (via live state)."""
        # We emulate by actually executing on the real state but recording
        # into trial; caller snapshots/restores.
        return _goto_impl(trial, m, dst)

    saved_state = set(state)
    saved_plan_len = [0]

    def _snapshot():
        return (set(state), len(plan))

    def _restore(snap):
        global state
        st, plen = snap
        state = set(st)
        del plan[plen:]

    def _goto_impl(trial, m, dst):
        while True:
            here = man_at(m)
            if here is None:
                return False
            if here == dst:
                return True
            p = path(here, dst)
            if p is None:
                return False
            for i in range(len(p) - 1):
                if len(plan) + 2 > 1000:
                    return False
                if not do_walk(p[i], p[i + 1], m):
                    return False

    def _ensure_spn(trial, m, spanner, nutloc, keep_after):
        """Make m hold a useable spanner at nutloc; optionally keep it."""
        if (("carrying", m, spanner) in state
                and ("useable", spanner) in state):
            return True
        sl = spanner_at(spanner)
        if sl is not None:
            if not _goto_impl(trial, m, sl):
                return False
            if not do_pickup(sl, spanner, m):
                return False
            return True
        # carried but not useable, or not here: try any useable spanner
        for s in start_spanners:
            if ("useable", s) in state:
                loc = spanner_at(s)
                if loc is None:
                    # carried by someone; only usable if it is our man
                    if ("carrying", m, s) in state:
                        return True
                    continue
                if not _goto_impl(trial, m, loc):
                    return False
                if not do_pickup(loc, s, m):
                    return False
                return True
        return False

    def _tight(trial, m, spanner, nut):
        nutloc = nut_at(nut)
        if nutloc is None:
            return False
        if not _goto_impl(trial, m, nutloc):
            return False
        return do_tighten(nutloc, spanner, m, nut)

    result = None
    snap = _snapshot()
    result = search()
    if result is None:
        _restore(snap)
        return []
    final = list(plan)
    _restore(snap)
    return final[:1000]