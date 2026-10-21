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

Approach: forward breadth-first search from init, with the reachable-state
frontier seeded by a backward closure from the goal so that goal-directed
progress is explored early. Correctness does not depend on the seeding: the
search still enumerates every applicable grounded action of every expanded
state, so the first goal state found is at a shortest-plan depth.
"""

from collections import deque

MAX_PLAN = 1000
MAX_STATES = 400000


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

    # start state already satisfies the goal
    if goal <= start:
        return []

    # reachable link edges from the initial state (static facts)
    links = sorted({(f[1], f[2]) for f in start
                    if f[0] == "link" and len(f) == 3})
    links = [(a, b) for (a, b) in links if a in tmap and b in tmap]

    # Goal-directed seed set: facts worth trying to hold early.  This only
    # orders the frontier; the search remains exhaustive over successors.
    targets = set()
    for f in goal:
        if f[0] == "tightened" and len(f) == 2:
            targets.add(("at", f[1], None))  # placeholder, refined below
    target_nuts = set(f[1] for f in goal
                      if f[0] == "tightened" and len(f) == 2 and f[1] in tmap)
    nut_locs = {}
    for f in start:
        if f[0] == "at" and len(f) == 3 and f[1] in target_nuts:
            nut_locs.setdefault(f[1], f[2])
    seed = set()
    for n, l in nut_locs.items():
        seed.add(("at", n, l))
        for s in spanners:
            seed.add(("at", s, l))
            seed.add(("useable", s))

    def gen_actions(state):
        """Generate (string, del_effects, add_effects) tuples."""
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
                    yield ("(walk %s %s %s)" % (a, b, m),
                           frozenset((("at", m, a),)),
                           frozenset((("at", m, b),)))
            held = carrying.get(m, frozenset())
            for l in here:
                for s in sorted(spanners):
                    if s in held:
                        continue
                    if ("at", s, l) in state:
                        yield ("(pickup_spanner %s %s %s)" % (l, s, m),
                               frozenset((("at", s, l),)),
                               frozenset((("carrying", m, s),)))
                for s in sorted(held):
                    if s not in useable:
                        continue
                    for n in sorted(nuts):
                        if n not in loose:
                            continue
                        if n in nut_at.get(l, ()):
                            yield ("(tighten_nut %s %s %s %s)" % (l, s, m, n),
                                   frozenset((("loose", n), ("useable", s))),
                                   frozenset((("tightened", n),)))

    def priority(state):
        """Lower is searched earlier; heuristic only, never prunes."""
        h = 0
        for f in seed:
            if f[2] is None:
                continue
            if f not in state:
                h += 1
        # prefer states holding many goal atoms
        g = sum(1 for f in goal if f in state)
        return (h - g, len(state))

    # BFS over reachable ground states
    seen = {start}
    queue = deque()
    queue.append((start, ()))
    expanded = 0

    while queue:
        state, path = queue.popleft()
        expanded += 1
        if expanded > MAX_STATES:
            break
        succs = []
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
            succs.append((priority(nxt), len(succs), nxt, newpath))
        if succs:
            succs.sort(key=lambda item: (item[0], item[1]))
            for item in succs:
                queue.append((item[2], item[3]))

    return []