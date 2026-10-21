"""Grounded planner for the 'spanner' planning domain.

Public contract:
    get_plan(objects, init, goal) -> list[str]

`objects` is a collection of (name, type) pairs; `init` and `goal` are
collections of predicate tuples (given as arrays in JSON).  The returned plan
is a list of parenthesized grounded action strings, using exactly the argument
order given in the domain definition.

Strategy: a deterministic, state-serialising greedy plan builder.  Each man
handles its share of the still-loose goal nuts; for every nut it walks along a
shortest directed link path to a useable spanner, picks it up (and drops it
after use since tightening makes it unusable), walks to the nut and tightens
it.  All decisions read the live state; nothing depends on set iteration
order (every candidate choice is sorted) and the inputs are never mutated.
"""

import collections


def _fmt(action, args):
    return "(" + " ".join([action] + [str(a) for a in args]) + ")"


def get_plan(objects, init, goal):
    # ------------------------------------------------------------------
    # Typed, immutable view of the input.
    # ------------------------------------------------------------------
    types = {}
    for pair in objects:
        name = pair[0]
        tname = pair[1]
        types.setdefault(name, set()).add(tname)

    def isa(obj, tname):
        return tname in types.get(obj, ())

    state = set()
    for fact in init:
        state.add(tuple(fact))

    goal_facts = set(tuple(g) for g in goal)

    locations = sorted(n for n in types if isa(n, "location"))
    nuts = sorted(n for n in types if isa(n, "nut"))
    spanners = sorted(n for n in types if isa(n, "spanner"))
    men = sorted(n for n in types if isa(n, "man"))

    links = collections.defaultdict(set)
    for fact in list(state):
        if fact[0] == "link":
            links[fact[1]].add(fact[2])

    plan = []
    LIMIT = 1000

    # ------------------------------------------------------------------
    # Grounded actions: precondition check, effect application, emission.
    # ------------------------------------------------------------------
    def do_walk(start, end, m):
        if ("at", m, start) not in state or ("link", start, end) not in state:
            return False
        if len(plan) + 1 > LIMIT:
            return False
        state.discard(("at", m, start))
        state.add(("at", m, end))
        plan.append(_fmt("walk", (start, end, m)))
        return True

    def do_pickup(l, s, m):
        if ("at", m, l) not in state or ("at", s, l) not in state:
            return False
        if ("carrying", m, s) in state:
            return True
        if len(plan) + 1 > LIMIT:
            return False
        state.discard(("at", s, l))
        state.add(("carrying", m, s))
        plan.append(_fmt("pickup_spanner", (l, s, m)))
        return True

    def do_drop(l, s, m):
        if ("carrying", m, s) not in state:
            return False
        if ("at", s, l) in state:
            return True
        if len(plan) + 1 > LIMIT:
            return False
        state.discard(("carrying", m, s))
        state.add(("at", s, l))
        plan.append(_fmt("drop_spanner", (l, s, m)))
        return True

    def do_tighten(l, s, m, n):
        if (("at", m, l) not in state or ("at", n, l) not in state
                or ("carrying", m, s) not in state
                or ("useable", s) not in state
                or ("loose", n) not in state):
            return False
        if len(plan) + 1 > LIMIT:
            return False
        state.discard(("loose", n))
        state.discard(("useable", s))
        state.add(("tightened", n))
        plan.append(_fmt("tighten_nut", (l, s, m, n)))
        return True

    # ------------------------------------------------------------------
    # State queries.
    # ------------------------------------------------------------------
    def man_at(m):
        best = None
        for f in list(state):
            if f[0] == "at" and f[1] == m and isa(f[2], "location"):
                if best is None or f[2] < best:
                    best = f[2]
        return best

    def nut_at(n):
        for f in list(state):
            if f[0] == "at" and f[1] == n and isa(f[2], "location"):
                return f[2]
        return None

    def spanner_at(s):
        for f in list(state):
            if f[0] == "at" and f[1] == s and isa(f[2], "location"):
                return f[2]
        return None

    def carrying_of(m):
        out = []
        for f in sorted(state):
            if f[0] == "carrying" and f[1] == m:
                out.append(f[2])
        return sorted(set(out))

    def path(src, dst):
        """Deterministic breadth-first shortest route (directed links)."""
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
        """Walk man m to dst along a shortest link path."""
        for _ in range(len(locations) + 2):
            here = man_at(m)
            if here is None or here == dst:
                return here == dst
            p = path(here, dst)
            if p is None:
                return False
            for i in range(len(p) - 1):
                if not do_walk(p[i], p[i + 1], m):
                    return False
        return False

    # ------------------------------------------------------------------
    # Greedy subtask: make m hold a useable spanner, then tighten nut n.
    # ------------------------------------------------------------------
    def useable_spanners():
        return sorted(s for s in spanners if ("useable", s) in state)

    def acquire_spanner(m):
        """Return a spanner carried by m that is still useable, or None.

        Prefers the closest reachable useable spanner lying on the ground,
        then any already-carried useable spanner.
        """
        best = None
        here = man_at(m)
        if here is None:
            return None
        for s in useable_spanners():
            loc = spanner_at(s)
            if loc is None:
                continue
            p = path(here, loc)
            if p is None:
                continue
            key = (len(p), loc, s)
            if best is None or key < best[0]:
                best = (key, s, loc, p)
        if best is not None:
            _key, s, loc, p = best
            for i in range(len(p) - 1):
                if not do_walk(p[i], p[i + 1], m):
                    return None
            if do_pickup(loc, s, m):
                return s
            return None
        for s in carrying_of(m):
            if ("useable", s) in state:
                return s
        return None

    def tighten_one(m, n):
        """Bring m to nut n's location and tighten it with a useable spanner."""
        nl = nut_at(n)
        if nl is None:
            return False
        s = None
        for cand in carrying_of(m):
            if ("useable", cand) in state:
                s = cand
                break
        if s is None:
            here = man_at(m)
            # go to a useable spanner first, then to the nut
            s = acquire_spanner(m)
            if s is None:
                return False
            if not goto(m, nl):
                return False
            if ("carrying", m, s) not in state:
                return False
            if do_tighten(nl, s, m, n):
                return True
            return False
        if not goto(m, nl):
            return False
        if do_tighten(nl, s, m, n):
            return True
        # Spanner unusable on arrival (should not happen); try another.
        return False

    def drop_all(m):
        here = man_at(m)
        if here is None:
            return
        for s in carrying_of(m):
            do_drop(here, s, m)

    # ------------------------------------------------------------------
    # Main loop.
    # ------------------------------------------------------------------
    goal_nuts = [n for n in nuts if ("tightened", n) in goal_facts]

    def pending_nuts():
        return [n for n in goal_nuts
                if ("loose", n) in state and ("tightened", n) not in state]

    # Assign nuts round-robin to men so work is spread over available men.
    if men:
        for idx, m in enumerate(men):
            todo = [n for i, n in enumerate(pending_nuts())
                    if i % len(men) == idx]
            for n in todo:
                if len(plan) >= LIMIT:
                    break
                if ("tightened", n) in state or ("loose", n) not in state:
                    continue
                tighten_one(m, n)
                drop_all(m)
            if len(plan) >= LIMIT:
                break

    # Fallback: any remaining untightened goal nut is attempted once more by
    # each man in turn (handles odd reachable/multi-man configurations).
    if any((("tightened", n) in goal_facts and ("tightened", n) not in state)
           for n in nuts):
        for n in goal_nuts:
            if ("tightened", n) in state:
                continue
            for m in men:
                if len(plan) >= LIMIT:
                    break
                tighten_one(m, n)
                drop_all(m)
                if ("tightened", n) in state:
                    break

    return plan[:LIMIT]