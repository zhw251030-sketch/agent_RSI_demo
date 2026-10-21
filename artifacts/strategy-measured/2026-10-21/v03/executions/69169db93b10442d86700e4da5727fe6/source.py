"""Grounded planner for the "spanner" planning domain.

Public contract
---------------
get_plan(objects, init, goal) -> list[str]

* objects : iterable of (name, type_name) pairs.
* init    : iterable of predicate tuples, e.g. ("at", "bob", "shed").
* goal    : iterable of predicate tuples.
* returns a list of at most 1000 grounded action strings, each fully
  parenthesized, e.g. "(walk shed location1 bob)".

Only the standard library is used.  Inputs are never mutated and no reliance
is placed on set iteration order (everything derived from user input is
sorted).
"""

from collections import deque

MAX_ACTIONS = 1000


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _facts(pairs):
    """Normalize an iterable of predicate tuples into a set of tuples."""
    out = set()
    for p in pairs:
        out.add(tuple(p))
    return out


def _types(objects):
    """Map every declared object name to its type (deterministic)."""
    t = {}
    for pair in objects:
        name = pair[0]
        typ = pair[1]
        t[name] = typ
    return t


def _by_type(types, wanted):
    """Sorted list of object names whose type is exactly `wanted`."""
    return sorted(n for n, ty in types.items() if ty == wanted)


def _subtypes(types, name):
    """Return the set of types the given object is compatible with.

    The domain hierarchy is small and fixed:
        object
          location
          locatable
            man
            nut
            spanner
    """
    ty = types.get(name)
    if ty is None:
        return set()
    out = {ty, "object"}
    if ty in ("man", "nut", "spanner"):
        out.add("locatable")
    return out


def _applicable(obj, types, want):
    """True if `obj` can fill a parameter of type `want`."""
    return want in _subtypes(types, obj)


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------

class _State(object):
    __slots__ = ("at", "carrying", "useable", "tightened", "loose")

    def __init__(self, at, carrying, useable, tightened, loose):
        self.at = at            # set of (locatable, location)
        self.carrying = carrying  # set of (man, spanner)
        self.useable = useable    # set of spanner
        self.tightened = tightened  # set of nut
        self.loose = loose        # set of nut

    def key(self):
        return (
            frozenset(self.at),
            frozenset(self.carrying),
            frozenset(self.useable),
            frozenset(self.tightened),
            frozenset(self.loose),
        )

    def copy(self):
        return _State(set(self.at), set(self.carrying), set(self.useable),
                      set(self.tightened), set(self.loose))


def _read_state(init):
    at = set()
    carrying = set()
    useable = set()
    tightened = set()
    loose = set()
    for f in init:
        if not f:
            continue
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
        if not f:
            continue
        name = f[0]
        args = tuple(f[1:])
        out.add((name, args))
    return out


def _read_links(init):
    """Return a dict mapping each location to a sorted tuple of destinations."""
    links = {}
    for f in init:
        if not f:
            continue
        if f[0] == "link" and len(f) == 3:
            links.setdefault(f[1], set()).add(f[2])
    return {k: sorted(v) for k, v in links.items()}


def _goal_satisfied(state, gset):
    for name, args in gset:
        if name == "at":
            if (args[0], args[1]) not in state.at:
                return False
        elif name == "carrying":
            if (args[0], args[1]) not in state.carrying:
                return False
        elif name == "useable":
            if args[0] not in state.useable:
                return False
        elif name == "tightened":
            if args[0] not in state.tightened:
                return False
        elif name == "loose":
            if args[0] not in state.loose:
                return False
        else:
            # Unknown predicates are treated as unconstrained.
            return False
    return True


# --------------------------------------------------------------------------
# action generation (lazily expanded, deterministic order)
# --------------------------------------------------------------------------

def _actions(state, types, links):
    """Yield (action_string, resulting_state) pairs applicable in `state`."""
    at = state.at
    locations = _by_type(types, "location")
    men = _by_type(types, "man")
    nuts = _by_type(types, "nut")
    spanners = _by_type(types, "spanner")

    # ---- walk(start, end, man) ----
    for m in men:
        here = sorted(l for (who, l) in at if who == m)
        for start in here:
            if start not in locations:
                continue
            for end in links.get(start, ()):
                if end not in locations:
                    continue
                ns = state.copy()
                ns.at.discard((m, start))
                ns.at.add((m, end))
                yield ("(walk %s %s %s)" % (start, end, m), ns)

    # ---- pickup_spanner(loc, spanner, man) ----
    for s in spanners:
        for (obj, loc) in sorted(at):
            if obj != s:
                continue
            for m in sorted(who for (who, l) in at if l == loc):
                if m not in men:
                    continue
                ns = state.copy()
                ns.at.discard((s, loc))
                ns.carrying.add((m, s))
                yield ("(pickup_spanner %s %s %s)" % (loc, s, m), ns)

    # ---- tighten_nut(loc, spanner, man, nut) ----
    for n in nuts:
        if n not in state.loose:
            continue
        for (obj, loc) in sorted(at):
            if obj != n:
                continue
            for (m, s) in sorted(state.carrying):
                if s not in state.useable:
                    continue
                if (m, loc) not in at:
                    continue
                ns = state.copy()
                ns.loose.discard(n)
                ns.useable.discard(s)
                ns.tightened.add(n)
                yield ("(tighten_nut %s %s %s %s)" % (loc, s, m, n), ns)


# --------------------------------------------------------------------------
# public entry point
# --------------------------------------------------------------------------

def get_plan(objects, init, goal):
    types = _types(objects)
    init_set = _facts(init)
    goal_set = _read_goal(goal)
    links = _read_links(init_set)

    start = _read_state(init_set)

    if _goal_satisfied(start, goal_set):
        return []

    # Breadth-first search over the finite state space, expanding actions in
    # a deterministic (sorted) order.
    seen = {start.key()}
    frontier = deque()
    frontier.append((start, []))
    steps = 0

    while frontier:
        state, plan = frontier.popleft()
        if len(plan) >= MAX_ACTIONS - 1:
            continue
        for act, nxt in _actions(state, types, links):
            k = nxt.key()
            if k in seen:
                continue
            seen.add(k)
            new_plan = plan + [act]
            steps += 1
            if _goal_satisfied(nxt, goal_set):
                if len(new_plan) <= MAX_ACTIONS:
                    return new_plan
                return []
            frontier.append((nxt, new_plan))
            if steps > 200000:
                return []
    return []
