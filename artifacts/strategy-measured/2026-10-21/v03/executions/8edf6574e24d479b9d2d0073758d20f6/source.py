"""Grounded planner for the 'spanner' planning domain.

Public contract:
    get_plan(objects, init, goal) -> list[str]

`objects` is a collection of (name, type) pairs; `init` and `goal` are
collections of predicate tuples.  The returned plan is a list of
parenthesized grounded action strings, in the exact argument order given
by the domain definition.  Nothing else is returned, and no global
mutable planning state is kept between calls.
"""

import collections


def _fmt(action, args):
    return "(" + " ".join([action] + [str(a) for a in args]) + ")"


def get_plan(objects, init, goal):
    # ------------------------------------------------------------------
    # Typed, immutable world model built from the arguments.
    # ------------------------------------------------------------------
    types = collections.defaultdict(set)
    for pair in objects:
        pair = list(pair)
        types[pair[0]].add(pair[1])

    def isa(obj, tname):
        return tname in types.get(obj, ())

    state = set()
    for fact in init:
        fact = tuple(fact)
        if fact:
            state.add(fact)

    goal_facts = set(tuple(g) for g in goal if g)

    locations = sorted(n for n in types if isa(n, "location"))
    nuts = sorted(n for n in types if isa(n, "nut"))
    spanners = sorted(n for n in types if isa(n, "spanner"))
    men = sorted(n for n in types if isa(n, "man"))

    links = collections.defaultdict(set)
    for f in list(state):
        if f[0] == "link":
            links[f[1]].add(f[2])

    plan = []

    # ------------------------------------------------------------------
    # Grounded action appliers (domain-faithful effects on `state`).
    # ------------------------------------------------------------------
    def do_walk(start, end, m):
        if ("at", m, start) in state and ("link", start, end) in state:
            state.discard(("at", m, start))
            state.add(("at", m, end))
            plan.append(_fmt("walk", (start, end, m)))
            return True
        return False

    def do_pickup(l, s, m):
        if ("at", m, l) in state and ("at", s, l) in state:
            state.discard(("at", s, l))
            state.add(("carrying", m, s))
            plan.append(_fmt("pickup_spanner", (l, s, m)))
            return True
        return False

    def do_tighten(l, s, m, n):
        if (("at", m, l) in state and ("at", n, l) in state
                and ("carrying", m, s) in state
                and ("useable", s) in state and ("loose", n) in state):
            state.discard(("loose", n))
            state.discard(("useable", s))
            state.add(("tightened", n))
            plan.append(_fmt("tighten_nut", (l, s, m, n)))
            return True
        return False

    # ------------------------------------------------------------------
    # State inspection helpers.
    # ------------------------------------------------------------------
    def man_at(m):
        for f in sorted(state):
            if f[0] == "at" and f[1] == m and isa(f[2], "location"):
                return f[2]
        return None

    def obj_at(o):
        for f in sorted(state):
            if f[0] == "at" and f[1] == o and isa(f[2], "location"):
                return f[2]
        return None

    def path(src, dst):
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
        while True:
            here = man_at(m)
            if here is None or here == dst:
                return here == dst
            p = path(here, dst)
            if p is None:
                return False
            for i in range(len(p) - 1):
                if len(plan) >= 1000:
                    return False
                if not do_walk(p[i], p[i + 1], m):
                    return False

    # ------------------------------------------------------------------
    # Try to build a plan: pick a man, a spanner and a nut order, then
    # simulate on a snapshot-restored copy of the state.
    # ------------------------------------------------------------------
    initial = set(state)
    goal_nuts = [n for n in nuts if ("tightened", n) in goal_facts]
    pending = [n for n in goal_nuts if ("loose", n) in initial]

    def restore():
        state.clear()
        state.update(initial)
        del plan[:]

    def try_one(man, spanner, nut_order):
        restore()
        holding = None
        for nut in nut_order:
            nl = obj_at(nut)
            if nl is None:
                return False
            if holding is None:
                if not acquire(man, spanner, nl):
                    return False
                holding = spanner
            if not goto(man, nl):
                return False
            if not do_tighten(nl, holding, man, nut):
                return False
            if ("useable", holding) not in state:
                holding = None
        if not satisfied():
            return False
        return True

    def acquire(man, preferred, loc):
        """Ensure man holds a useable spanner while standing at loc."""
        if not goto(man, loc):
            return False
        order = ([preferred] if preferred in spanners else []) + list(spanners)
        tried = []
        for s in order:
            if s in tried:
                continue
            tried.append(s)
            if ("carrying", man, s) in state and ("useable", s) in state:
                return True
            sl = obj_at(s)
            if sl is None:
                continue
            if not goto(man, sl):
                return False
            if not do_pickup(sl, s, man):
                continue
            if ("useable", s) in state:
                return goto(man, loc)
            # spanner consumed elsewhere; keep looking
            goto(man, loc)
        return False

    def satisfied():
        for g in goal_facts:
            if g not in state:
                return False
        return True

    def nut_orders(items):
        if len(items) <= 1:
            yield list(items)
            return
        for i, n in enumerate(items):
            rest = items[:i] + items[i + 1:]
            for sub in nut_orders(rest):
                yield [n] + sub

    orders = [list(pending)]
    if len(pending) <= 6:
        orders = list(nut_orders(pending))

    result = None
    for order in orders:
        for man in men:
            for spanner in (list(spanners) + [None]):
                if try_one(man, spanner, order):
                    result = list(plan)
                    restore()
                    return result[:1000]
        if len(order) <= 1:
            continue
    restore()
    return result if result is not None else []