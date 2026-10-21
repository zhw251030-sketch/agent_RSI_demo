"""Grounded planner for the 'spanner' STRIPS planning domain.

Public contract
---------------
get_plan(objects, init, goal) -> list[str]

* objects: iterable of (name, type) pairs (sets of tuples in the real
  runtime; JSON examples use arrays).
* init, goal: iterables of predicate tuples, e.g. ("at", "bob", "shed").

The returned plan is a list of at most 1000 grounded action strings,
each fully parenthesized, using the argument order declared by the
domain:

    (walk <start> <end> <man>)
    (pickup_spanner <location> <spanner> <man>)
    (tighten_nut <location> <spanner> <man> <nut>)

Approach: breadth-first search over reachable ground states with lazily
generated action instances, so the first solution found is shortest.
"""

from collections import deque

MAX_PLAN = 1000
MAX_STATES = 200000


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _as_tuple_set(facts):
    """Normalize a fact collection into a frozenset of tuples."""
    out = set()
    if facts is None:
        return frozenset(out)
    for f in facts:
        if f is None:
            continue
        if isinstance(f, str):
            continue
        try:
            out.add(tuple(f))
        except TypeError:
            continue
    return frozenset(out)


def _types(objects):
    """Map every object name to its declared type string."""
    t = {}
    if objects is None:
        return t
    for pair in objects:
        if pair is None or isinstance(pair, str):
            continue
        try:
            name, typ = pair[0], pair[1]
        except (TypeError, IndexError, KeyError):
            continue
        t[name] = typ
    return t


def _apply(state, del_effects, add_effects):
    return (state - del_effects) | add_effects


# --------------------------------------------------------------------------
# planner
# --------------------------------------------------------------------------

def get_plan(objects, init, goal):
    tmap = _types(objects)
    start = _as_tuple_set(init)
    goal = _as_tuple_set(goal)

    men = sorted(n for n, ty in tmap.items() if ty == "man")
    locs = sorted(n for n, ty in tmap.items() if ty == "location")
    spanners = sorted(n for n, ty in tmap.items() if ty == "spanner")
    nuts = sorted(n for n, ty in tmap.items() if ty == "nut")
    loc_set = set(locs)
    nut_set = set(nuts)

    if not men or not locs:
        return []

    if not goal or goal <= start:
        return []

    # Directed, static link edges from the initial state.
    links = sorted({(f[1], f[2]) for f in start
                    if len(f) == 3 and f[0] == "link"
                    and f[1] in loc_set and f[2] in loc_set})

    def gen_actions(state):
        at_m = {}
        carrying = {}
        nut_at = {}
        useable = set()
        loose = set()
        for f in state:
            if len(f) == 3 and f[0] == "at":
                at_m.setdefault(f[1], set()).add(f[2])
                nut_at.setdefault(f[2], set()).add(f[1])
            elif len(f) == 3 and f[0] == "carrying":
                carrying.setdefault(f[1], set()).add(f[2])
            elif len(f) == 2 and f[0] == "useable":
                useable.add(f[1])
            elif len(f) == 2 and f[0] == "loose":
                loose.add(f[1])

        for m in men:
            here = at_m.get(m, frozenset())
            if not here:
                continue
            for (a, b) in links:
                if a in here:
                    yield ("(walk %s %s %s)" % (a, b, m),
                           frozenset((("at", m, a),)),
                           frozenset((("at", m, b),)))
            held = carrying.get(m, frozenset())
            for l in here:
                for s in spanners:
                    if s not in held and ("at", s, l) in state:
                        yield ("(pickup_spanner %s %s %s)" % (l, s, m),
                               frozenset((("at", s, l),)),
                               frozenset((("carrying", m, s),)))
                if held:
                    here_nuts = nut_at.get(l, frozenset())
                    for s in sorted(held):
                        if s not in useable:
                            continue
                        for n in nuts:
                            if n in loose and n in here_nuts:
                                yield ("(tighten_nut %s %s %s %s)"
                                       % (l, s, m, n),
                                       frozenset((("loose", n),
                                                  ("useable", s))),
                                       frozenset((("tightened", n),)))

    seen = {start}
    queue = deque()
    queue.append((start, ()))
    expanded = 0

    while queue:
        state, path = queue.popleft()
        expanded += 1
        if expanded > MAX_STATES:
            break
        for astr, dele, adde in gen_actions(state):
            nxt = _apply(state, dele, adde)
            if nxt in seen:
                continue
            seen.add(nxt)
            newpath = path + (astr,)
            if len(newpath) > MAX_PLAN:
                continue
            if goal <= nxt:
                return list(newpath)
            queue.append((nxt, newpath))

    return []