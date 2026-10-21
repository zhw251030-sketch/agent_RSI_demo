"""Grounded planner for the "spanner" planning domain.

Public contract
---------------
get_plan(objects, init, goal) -> list[str]

* objects : iterable of (name, type_name) pairs.
* init    : iterable of predicate tuples, e.g. ("at", "bob", "shed").
* goal    : iterable of predicate tuples.
* returns a list of at most 1000 grounded action strings, each fully
  parenthesized, e.g. "(walk shed location1 bob)".

Only the standard library is used.  Inputs are never mutated and nothing
depends on set iteration order: every derived collection is sorted.
"""

from collections import deque

MAX_ACTIONS = 1000
MAX_EXPANSIONS = 200000

LOCATABLE_TYPES = ("man", "nut", "spanner")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _facts(pairs):
    """Normalize an iterable of predicate tuples into a set of tuples."""
    out = set()
    for p in pairs:
        if p:
            out.add(tuple(p))
    return out


def _types(objects):
    """Map every declared object name to its declared type."""
    t = {}
    for pair in objects:
        if not pair:
            continue
        t[pair[0]] = pair[1]
    return t


def _by_type(types, wanted):
    """Sorted names whose declared type is exactly `wanted`."""
    return sorted(n for n, ty in types.items() if ty == wanted)


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------

class _State(object):
    __slots__ = ("at", "carrying", "useable", "tightened", "loose")

    def __init__(self, at, carrying, useable, tightened, loose):
        self.at = at               # {(locatable, location)}
        self.carrying = carrying   # {(man, spanner)}
        self.useable = useable     # {spanner}
        self.tightened = tightened  # {nut}
        self.loose = loose         # {nut}

    def key(self):
        return (frozenset(self.at),
                frozenset(self.carrying),
                frozenset(self.useable),
                frozenset(self.tightened),
                frozenset(self.loose))

    def copy(self):
        return _State(set(self.at), set(self.carrying), set(self.useable),
                      set(self.tightened), set(self.loose))


def _read_state(init_set):
    at = set()
    carrying = set()
    useable = set()
    tightened = set()
    loose = set()
    for f in init_set:
        name = f[0]
        args = f[1:]
        if name == "at" and len(args) == 2:
            at.add((args[0], args[1]))
        elif name == "carrying" and len(args) == 2:
            carrying.add((args[0], args[1]))
        elif name == "useable" and len(args) == 1:
            useable.add(args[0])
        elif name == "tightened" and len(args) == 1:
            tightened.add(args[0])
        elif name == "loose" and len(args) == 1:
            loose.add(args[0])
    return _State(at, carrying, useable, tightened, loose)


def _read_goal(goal):
    out = set()
    for f in goal:
        if f:
            out.add((f[0], tuple(f[1:])))
    return out


def _goal_satisfied(state, gset):
    for name, args in gset:
        if name == "at":
            if len(args) != 2 or (args[0], args[1]) not in state.at:
                return False
        elif name == "carrying":
            if len(args) != 2 or (args[0], args[1]) not in state.carrying:
                return False
        elif name == "useable":
            if len(args) != 1 or args[0] not in state.useable:
                return False
        elif name == "tightened":
            if len(args) != 1 or args[0] not in state.tightened:
                return False
        elif name == "loose":
            if len(args) != 1 or args[0] not in state.loose:
                return False
        else:
            # Unknown predicates are treated as unconstrained goals.
            return False
    return True


# --------------------------------------------------------------------------
# grounded operators
# --------------------------------------------------------------------------

def _walk(state, locations, men, links):
    """(walk ?start ?end ?m)"""
    at = state.at
    for m in men:
        here = sorted(l for (who, l) in at if who == m and l in locations)
        for start in here:
            for end in links.get(start, ()):
                if end not in locations:
                    continue
                ns = state.copy()
                ns.at.discard((m, start))
                ns.at.add((m, end))
                yield ("(walk %s %s %s)" % (start, end, m), ns)


def _pickup_spanner(state, locations, men, spanners):
    """(pickup_spanner ?l ?s ?m)"""
    at = state.at
    for s in spanners:
        where = sorted(l for (obj, l) in at if obj == s and l in locations)
        for loc in where:
            for m in sorted(who for (who, l) in at if l == loc):
                if m not in men:
                    continue
                ns = state.copy()
                ns.at.discard((s, loc))
                ns.carrying.add((m, s))
                yield ("(pickup_spanner %s %s %s)" % (loc, s, m), ns)


def _tighten_nut(state, locations, men, nuts, spanners):
    """(tighten_nut ?l ?s ?m ?n)"""
    at = state.at
    for n in nuts:
        if n not in state.loose:
            continue
        where = sorted(l for (obj, l) in at if obj == n and l in locations)
        for loc in where:
            for m in sorted(who for (who, l) in at if l == loc):
                if m not in men:
                    continue
                for s in spanners:
                    if (m, s) not in state.carrying:
                        continue
                    if s not in state.useable:
                        continue
                    ns = state.copy()
                    ns.loose.discard(n)
                    ns.useable.discard(s)
                    ns.tightened.add(n)
                    yield ("(tighten_nut %s %s %s %s)" % (loc, s, m, n), ns)


def _actions(state, ctx):
    kinds = []
    kinds.extend(_walk(state, ctx["locations"], ctx["men"], ctx["links"]))
    kinds.extend(_pickup_spanner(state, ctx["locations"], ctx["men"],
                                 ctx["spanners"]))
    kinds.extend(_tighten_nut(state, ctx["locations"], ctx["men"],
                              ctx["nuts"], ctx["spanners"]))
    return kinds


# --------------------------------------------------------------------------
# public entry point
# --------------------------------------------------------------------------

def get_plan(objects, init, goal):
    types = _types(objects)
    init_set = _facts(init)
    gset = _read_goal(goal)

    links = {}
    for f in init_set:
        if f[0] == "link" and len(f) == 3:
            links.setdefault(f[1], set()).add(f[2])
    links = dict((k, sorted(v)) for k, v in links.items())

    ctx = {
        "locations": set(_by_type(types, "location")),
        "men": set(_by_type(types, "man")),
        "nuts": set(_by_type(types, "nut")),
        "spanners": set(_by_type(types, "spanner")),
        "links": links,
    }

    start = _read_state(init_set)
    if _goal_satisfied(start, gset):
        return []

    seen = set([start.key()])
    frontier = deque()
    frontier.append((start, ()))
    expansions = 0

    while frontier:
        state, plan = frontier.popleft()
        if len(plan) >= MAX_ACTIONS - 1:
            continue
        expansions += 1
        if expansions > MAX_EXPANSIONS:
            break
        for act, nxt in _actions(state, ctx):
            k = nxt.key()
            if k in seen:
                continue
            seen.add(k)
            new_plan = plan + (act,)
            if _goal_satisfied(nxt, gset):
                return list(new_plan)
            frontier.append((nxt, new_plan))
    return []