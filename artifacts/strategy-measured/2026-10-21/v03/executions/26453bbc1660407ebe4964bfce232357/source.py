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

Approach: a domain-specific greedy/ordered construction over ground facts,
followed by a breadth-first fallback search over reachable ground states.
Only facts reachable from init are ever used, and links are treated as
directed exactly as declared.
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


def _neighbors(loc, links_out):
    return links_out.get(loc, ())


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

    links_out = {}
    for f in start:
        if f[0] == "link" and len(f) == 3:
            a, b = f[1], f[2]
            if tmap.get(a) == "location" and tmap.get(b) == "location":
                links_out.setdefault(a, []).append(b)
    for a in links_out:
        links_out[a] = sorted(set(links_out[a]))

    # forward closure of locations reachable by following links from any
    # location that holds a fact of interest (nuts or spanners or men).
    def bfs_dist(sources):
        dist = {}
        frontier = []
        for s in sources:
            if s not in dist:
                dist[s] = 0
                frontier.append(s)
        d = 0
        while frontier:
            d += 1
            nxt = []
            for l in frontier:
                for nb in _neighbors(l, links_out):
                    if nb not in dist:
                        dist[nb] = d
                        nxt.append(nb)
            frontier = nxt
        return dist

    # ---- state interpretation helpers -----------------------------------
    def read(state):
        man_at = {}
        spanner_at = {}
        nut_at = {}
        carrying = {}
        useable = set()
        loose = set()
        for f in state:
            p = f[0]
            if p == "at" and len(f) == 3:
                x, l = f[1], f[2]
                ty = tmap.get(x)
                if ty == "man":
                    man_at.setdefault(x, set()).add(l)
                elif ty == "spanner":
                    spanner_at.setdefault(x, set()).add(l)
                elif ty == "nut":
                    nut_at.setdefault(x, set()).add(l)
            elif p == "carrying" and len(f) == 3:
                carrying.setdefault(f[1], set()).add(f[2])
            elif p == "useable" and len(f) == 2:
                useable.add(f[1])
            elif p == "loose" and len(f) == 2:
                loose.add(f[1])
        return man_at, spanner_at, nut_at, carrying, useable, loose

    def gen_actions(state):
        man_at, spanner_at, nut_at, carrying, useable, loose = read(state)
        for m in men:
            here = man_at.get(m, frozenset())
            for l in sorted(here):
                for b in _neighbors(l, links_out):
                    yield ("(walk %s %s %s)" % (l, b, m),
                           frozenset((("at", m, l),)),
                           frozenset((("at", m, b),)))
            held = carrying.get(m, frozenset())
            for l in sorted(here):
                for s in sorted(spanner_at):
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
                        if ("at", n, l) in state:
                            yield ("(tighten_nut %s %s %s %s)" % (l, s, m, n),
                                   frozenset((("loose", n),
                                              ("useable", s))),
                                   frozenset((("tightened", n),)))

    def search():
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
        return None

    # ---- structured construction ---------------------------------------
    def construct():
        """Deterministic constructive plan honouring resource consumption.

        Spanners become unusable once used, so each un-tightened nut is
        assigned a distinct still-usable spanner reachable in time.
        """
        state = set(start)
        plan = []
        man = men[0]
        need = sorted(n for n in nuts if ("loose", n) in state)
        tightened = 0
        guard = 0
        while need and guard < 4 * (len(nuts) + 2) * (len(locs) + 2):
            guard += 1
            nut = need[0]
            nut_loc_list = sorted(l for l in locs if ("at", nut, l) in state)
            if not nut_loc_list:
                return None
            target = None
            for l in nut_loc_list:
                for s in sorted(spanners):
                    if ("useable", s) not in state:
                        continue
                    sp_locs = sorted(x for x in locs if ("at", s, x) in state)
                    if not sp_locs:
                        continue
                    here = sorted(l2 for l2 in locs if ("at", man, l2) in state)
                    if not here:
                        return None
                    dist = bfs_dist(here)
                    best = None
                    for sl in sp_locs:
                        d1 = dist.get(sl)
                        if d1 is None:
                            continue
                        d2 = bfs_dist([sl]).get(l)
                        if d2 is None:
                            continue
                        cost = d1 + d2
                        if best is None or cost < best[0]:
                            best = (cost, sl)
                    if best is not None:
                        target = (s, best[1], l)
                        break
            if target is None:
                return None
            s, sp_loc, nut_loc = target
            here = sorted(l2 for l2 in locs if ("at", man, l2) in state)
            cur = here[0]
            for step in _walk_path(cur, sp_loc, links_out):
                plan.append(step)
                state.discard(("at", man, cur))
                nxt_loc = step[1]
                state.add(("at", man, nxt_loc))
                cur = nxt_loc
            if ("at", s, cur) not in state:
                return None
            plan.append("(pickup_spanner %s %s %s)" % (cur, s, man))
            state.discard(("at", s, cur))
            state.add(("carrying", man, s))
            for step in _walk_path(cur, nut_loc, links_out):
                plan.append(step)
                state.discard(("at", man, cur))
                nxt_loc = step[1]
                state.add(("at", man, nxt_loc))
                cur = nxt_loc
            if ("at", nut, cur) not in state:
                return None
            plan.append("(tighten_nut %s %s %s %s)" % (cur, s, man, nut))
            state.discard(("loose", nut))
            state.discard(("useable", s))
            state.add(("tightened", nut))
            need = [n for n in need if ("loose", n) in state]
            tightened += 1
            if len(plan) > MAX_PLAN:
                return None
        if need:
            return None
        if not goal <= frozenset(state):
            return None
        return plan

    def _walk_path(src, dst, links):
        """Shortest directed walk from src to dst, or None."""
        if src == dst:
            return []
        prev = {src: None}
        frontier = [src]
        while frontier:
            nxt = []
            for l in frontier:
                for nb in links.get(l, ()):
                    if nb not in prev:
                        prev[nb] = l
                        nxt.append(nb)
            if dst in prev:
                path = []
                cur = dst
                while prev[cur] is not None:
                    path.append(cur)
                    cur = prev[cur]
                path.reverse()
                return ["(walk %s %s %s)" % (a, b, man)
                        for a, b in zip([src] + path[:-1], path)]
            frontier = nxt
        return None

    built = construct()
    if built is not None:
        return built

    found = search()
    if found is not None:
        return found
    return []