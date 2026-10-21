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

Approach: breadth-first search over the set of ground states reachable
from init, with ground action instances generated lazily per state.
BFS yields a shortest plan, which keeps the answer small and robust.
"""

from collections import deque
from itertools import permutations

MAX_PLAN = 1000
MAX_STATES = 300000


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _as_tuple_set(facts):
    """Normalize a fact collection into a frozenset of tuples."""
    out = set()
    for f in facts:
        if isinstance(f, str):
            continue
        out.add(tuple(f))
    return frozenset(out)


def _types(objects):
    """Map every object name to its declared type string."""
    t = {}
    for pair in objects:
        name, typ = pair[0], pair[1]
        t[name] = typ
    return t


def _is(tmap, name, typ):
    return tmap.get(name) == typ


def _apply(state, del_effects, add_effects):
    return (state - del_effects) | add_effects


# --------------------------------------------------------------------------
# planner
# --------------------------------------------------------------------------

def get_plan(objects, init, goal):
    tmap = _types(objects)
    start = _as_tuple_set(init)
    goal = _as_tuple_set(goal)

    men = sorted(n for n in tmap if _is(tmap, n, "man"))
    locs = sorted(n for n in tmap if _is(tmap, n, "location"))
    spanners = sorted(n for n in tmap if _is(tmap, n, "spanner"))
    nuts = sorted(n for n in tmap if _is(tmap, n, "nut"))

    if not men or not locs:
        return []

    # start heuristic: already satisfied
    if goal <= start:
        return []

    # reachable link edges from the initial state
    links = sorted({(f[1], f[2]) for f in start
                    if f[0] == "link" and len(f) == 3})
    links = [(a, b) for (a, b) in links if a in tmap and b in tmap]

    useable0 = frozenset(("useable", s) for s in spanners)

    # static spanner usability is dynamic (tighten consumes it), so it
    # lives in the state; everything above is state.

    def gen_actions(state):
        """Generate (name, string, del_effects, add_effects) tuples."""
        at_m = {}
        for f in state:
            if f[0] == "at" and len(f) == 3:
                at_m.setdefault(f[1], set()).add(f[2])
        carrying = {}
        for f in state:
            if f[0] == "carrying" and len(f) == 3:
                carrying.setdefault(f[1], set()).add(f[2])
        useable = set(f[1] for f in state if f[0] == "useable" and len(f) == 2)
        loose = set(f[1] for f in state if f[0] == "loose" and len(f) == 2)
        nut_at = {}
        for f in state:
            if f[0] == "at" and len(f) == 3:
                nut_at.setdefault(f[2], set()).add(f[1])

        for m in men:
            here = at_m.get(m, frozenset())
            for (a, b) in links:
                if a in here:
                    yield ("walk", "(walk %s %s %s)" % (a, b, m),
                           frozenset((("at", m, a),)),
                           frozenset((("at", m, b),)))
            held = carrying.get(m, frozenset())
            for l in here:
                for s in sorted(spanners):
                    if s in held:
                        continue
                    if ("at", s, l) in state:
                        yield ("pickup_spanner",
                               "(pickup_spanner %s %s %s)" % (l, s, m),
                               frozenset((("at", s, l),)),
                               frozenset((("carrying", m, s),)))
                for s in sorted(held):
                    if s not in useable:
                        continue
                    for n in sorted(nuts):
                        if n not in loose:
                            continue
                        if n in nut_at.get(l, ()):
                            yield ("tighten_nut",
                                   "(tighten_nut %s %s %s %s)" % (l, s, m, n),
                                   frozenset((("loose", n),
                                              ("useable", s))),
                                   frozenset((("tightened", n),)))

    # BFS
    seen = {start}
    queue = deque()
    queue.append((start, ()))
    expanded = 0

    while queue:
        state, path = queue.popleft()
        expanded += 1
        if expanded > MAX_STATES:
            break
        for _name, astr, dele, adde in gen_actions(state):
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