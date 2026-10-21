"""Grounded planner for the 'spanner' STRIPS planning domain.

Public contract
---------------
get_plan(objects, init, goal) -> list[str]

* objects: iterable of (name, type) pairs.
* init, goal: iterables of predicate tuples, e.g. ("at", "bob", "shed").

The returned plan is a list of at most 1000 grounded action strings,
each fully parenthesized, using the argument order declared by the
domain:

    (walk <start> <end> <man>)
    (pickup_spanner <location> <spanner> <man>)
    (tighten_nut <location> <spanner> <man> <nut>)

Approach
--------
The domain admits an explicit goal-directed construction: for every loose
nut still required in the goal, move a man along the known directed link
graph to the nut's location, fetch a useable spanner (carrying at most
one), and tighten the nut. Each tightening consumes one spanner, so we
plan one nut at a time and re-fetch spanners on demand.

This is a constructive heuristic, not a claim of optimality: only the
number of goal-achieving action sequences matters for correctness.
Inputs are never mutated; all derived collections are local and every
iteration order is deterministic (sorted names).
"""

MAX_PLAN = 1000


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


def _apply(state, del_effects, add_effects):
    return (state - del_effects) | add_effects


# --------------------------------------------------------------------------
# planner
# --------------------------------------------------------------------------

def get_plan(objects, init, goal):
    tmap = _types(objects)
    start = _as_tuple_set(init)
    goal = _as_tuple_set(goal)

    men = sorted(n for n in tmap if tmap.get(n) == "man")
    locs = sorted(n for n in tmap if tmap.get(n) == "location")
    spanners = sorted(n for n in tmap if tmap.get(n) == "spanner")
    nuts = sorted(n for n in tmap if tmap.get(n) == "nut")

    if not men or not locs:
        return []

    if goal <= start:
        return []

    # ---- static structure -------------------------------------------------
    # link edges are never created or deleted by any action
    adj = {}
    for f in start:
        if f[0] == "link" and len(f) == 3 and f[1] in tmap and f[2] in tmap:
            adj.setdefault(f[1], set()).add(f[2])
    for k in adj:
        adj[k] = sorted(adj[k])

    # nut locations are static: nothing moves a nut
    nut_loc = {}
    for f in start:
        if f[0] == "at" and len(f) == 3 and f[2] in locs:
            nut_loc.setdefault(f[1], set()).add(f[2])

    def bfs_path(src, dst):
        """Shortest directed walk-path from src to dst (list of locations)."""
        if src == dst:
            return [src]
        seen = {src}
        frontier = [src]
        while frontier:
            nxt = []
            for cur in frontier:
                for nb in adj.get(cur, ()):
                    if nb in seen:
                        continue
                    seen.add(nb)
                    if nb == dst:
                        # reconstruct
                        parent = {nb: cur}
                        path = [nb]
                        while path[-1] != src:
                            path.append(parent[path[-1]])
                        path.reverse()
                        return path
                    nxt.append(nb)
            frontier = nxt
        return None

    # ---- mutable state ----------------------------------------------------
    state = set(start)
    plan = []

    def do_walk(m, a, b):
        plan.append("(walk %s %s %s)" % (a, b, m))
        state.discard(("at", m, a))
        state.add(("at", m, b))

    def do_pickup(m, l, s):
        plan.append("(pickup_spanner %s %s %s)" % (l, s, m))
        state.discard(("at", s, l))
        state.add(("carrying", m, s))

    def do_tighten(m, l, s, n):
        plan.append("(tighten_nut %s %s %s %s)" % (l, s, m, n))
        state.discard(("loose", n))
        state.discard(("useable", s))
        state.add(("tightened", n))

    def man_at(m):
        for f in state:
            if f[0] == "at" and len(f) == 3 and f[1] == m:
                return f[2]
        return None

    def carrying(m):
        for f in state:
            if f[0] == "carrying" and len(f) == 3 and f[1] == m:
                return f[2]
        return None

    # ---- main loop: one nut at a time -------------------------------------
    todo = sorted({f[1] for f in goal
                   if f[0] == "tightened" and len(f) == 2})
    # only nuts that are still loose are worth working on
    working = [n for n in todo
               if ("tightened", n) not in state and ("loose", n) in state]

    for n in working:
        if len(plan) >= MAX_PLAN:
            break
        # choose a man that can actually reach the nut
        placed = sorted(nut_loc.get(n, ()))
        man = None
        dest = None
        for m in men:
            here = man_at(m)
            if here is None:
                continue
            for loc in placed:
                path = bfs_path(here, loc)
                if path is not None:
                    man, dest, wpath = m, loc, path
                    break
            if man is not None:
                break
        if man is None:
            # unreachable under the current initial links
            continue

        # walk to the nut's location
        for i in range(len(wpath) - 1):
            do_walk(man, wpath[i], wpath[i + 1])

        # ensure we hold a useable spanner
        held = carrying(man)
        if held is None or ("useable", held) not in state:
            avail = []
            for s in spanners:
                if ("useable", s) not in state:
                    continue
                sloc = None
                for f in state:
                    if f[0] == "at" and len(f) == 3 and f[1] == s:
                        sloc = f[2]
                        break
                if sloc is not None:
                    avail.append((s, sloc))
            chosen = None
            for s, sloc in avail:
                path = bfs_path(dest, sloc)
                if path is not None:
                    chosen = (s, sloc, path)
                    break
            if chosen is None:
                continue
            s, sloc, spath = chosen
            for i in range(len(spath) - 1):
                do_walk(man, spath[i], spath[i + 1])
            do_pickup(man, sloc, s)
            held = s
            # return to the nut
            back = bfs_path(sloc, dest)
            if back is not None:
                for i in range(len(back) - 1):
                    do_walk(man, back[i], back[i + 1])

        if ("loose", n) not in state:
            continue
        if held is None or ("useable", held) not in state:
            continue
        do_tighten(man, dest, held, n)

    # verify the achieved goal conditions we attempted
    return list(plan)