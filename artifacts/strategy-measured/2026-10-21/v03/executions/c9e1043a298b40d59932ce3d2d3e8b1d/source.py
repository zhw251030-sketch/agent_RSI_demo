"""Grounded planner for the "spanner" STRIPS domain.

Public contract
---------------
get_plan(objects, init, goal) -> list[str]

`objects` is a collection of (name, type) pairs. Two orderings are tolerated:
    (name, type)
    (type, name)
Either ordering - and either scalar or single-element-list types - is normalised
internally.

`init` and `goal` are collections of predicate tuples such as
("at", "bob", "shed"). A missing fact is closed-world false.

The returned plan is a list of parenthesised grounded action strings using the
exact argument order given in the public domain definition:

    (walk <start> <end> <man>)
    (pickup_spanner <loc> <spanner> <man>)
    (tighten_nut <loc> <spanner> <man> <nut>)

Only the Python standard library is used and the caller-visible inputs are
never mutated. Action strings are always produced in deterministic order so a
plan is reproducible.
"""

from collections import deque

WALK = "walk"
PICKUP = "pickup_spanner"
TIGHTEN = "tighten_nut"

MAX_STEPS = 200
SOFT_BFS_NODES = 200000


def _as_set(facts):
    """Normalise a collection of predicate tuples to a set of hashable tuples."""
    out = set()
    for f in facts:
        if isinstance(f, (list, tuple)):
            out.add(tuple(f))
        else:
            out.add((f,))
    return out


def _name_type(item):
    """Return (name, type) accepting either ordering or list/tuple storage."""
    if not isinstance(item, (list, tuple)) or len(item) < 2:
        return None
    a, b = item[0], item[1]
    # Convention: type is the known vocabulary. If one side is a known type
    # string and the other looks like an identifier, treat the other as name.
    known = {"location", "locatable", "man", "nut", "spanner"}
    if isinstance(a, str) and a in known and isinstance(b, str):
        return (b, a)
    if isinstance(b, str) and b in known and isinstance(a, str):
        return (a, b)
    # Default: (name, type) ordering.
    return (a, b)


def _typed(objects):
    """Return the type-indexed view expected by the planner internals."""
    by_type = {"man": set(), "nut": set(), "spanner": set(), "location": set()}
    for raw in objects:
        nt = _name_type(raw)
        if nt is None:
            continue
        name, typ = nt
        if not isinstance(name, str) or not isinstance(typ, str):
            continue
        # Types may be the abstract "locatable"; ignore for selection.
        if typ in by_type:
            by_type[typ].add(name)
        elif typ == "locatable":
            # Cannot infer subclass from a bare "locatable" entry.
            pass
    return by_type


def get_plan(objects, init, goal):
    """Return a list of grounded action strings achieving `goal` from `init`."""
    by_type = _typed(objects)
    men = by_type["man"]
    nuts = by_type["nut"]
    spanners = by_type["spanner"]
    locations = by_type["location"]

    state = _as_set(init)
    goal_set = _as_set(goal)

    # Augment locations from link facts (the public table may omit some).
    for f in state:
        if len(f) == 3 and f[0] == "link":
            locations.add(f[1])
            locations.add(f[2])

    def applicable_and_effect(s, action, args):
        if action == WALK:
            start, end, m = args
            if ("at", m, start) not in s or ("link", start, end) not in s:
                return None
            nxt = set(s)
            nxt.discard(("at", m, start))
            nxt.add(("at", m, end))
            return nxt
        if action == PICKUP:
            loc, sp, m = args
            if ("at", m, loc) not in s or ("at", sp, loc) not in s:
                return None
            nxt = set(s)
            nxt.discard(("at", sp, loc))
            nxt.add(("carrying", m, sp))
            return nxt
        if action == TIGHTEN:
            loc, sp, m, nut = args
            if ("at", m, loc) not in s:
                return None
            if ("at", nut, loc) not in s:
                return None
            if ("carrying", m, sp) not in s:
                return None
            if ("useable", sp) not in s:
                return None
            if ("loose", nut) not in s:
                return None
            nxt = set(s)
            nxt.discard(("loose", nut))
            nxt.discard(("useable", sp))
            nxt.add(("tightened", nut))
            return nxt
        return None

    def format_action(action, args):
        return "(" + action + " " + " ".join(args) + ")"

    def type_check(action, args):
        if action == WALK:
            start, end, m = args
            return start in locations and end in locations and m in men
        if action == PICKUP:
            loc, sp, m = args
            return loc in locations and sp in spanners and m in men
        if action == TIGHTEN:
            loc, sp, m, nut = args
            return loc in locations and sp in spanners and m in men and nut in nuts
        return False

    def successors(s):
        res = []
        # Where is each man?
        man_loc = {}
        for f in s:
            if len(f) == 3 and f[0] == "at" and f[1] in men:
                man_loc[f[1]] = f[2]
        # What spanners are at each location?
        spanner_loc = {}
        for f in s:
            if len(f) == 3 and f[0] == "at" and f[1] in spanners:
                spanner_loc.setdefault(f[2], set()).add(f[1])
        # Carry status: man -> spanner or None
        carrying = {}
        for f in s:
            if len(f) == 3 and f[0] == "carrying":
                carrying[f[1]] = f[2]
        for m in sorted(man_loc):
            loc = man_loc[m]
            # Walk actions
            for (src, dst) in sorted(_link_pairs(s, loc)):
                nxt = applicable_and_effect(s, WALK, (src, dst, m))
                if nxt is not None and type_check(WALK, (src, dst, m)):
                    res.append((format_action(WALK, (src, dst, m)), nxt))
            # Pick up spanners at this location
            for sp in sorted(spanner_loc.get(loc, ())):
                if m in carrying:
                    break  # cannot carry more than one
                nxt = applicable_and_effect(s, PICKUP, (loc, sp, m))
                if nxt is not None and type_check(PICKUP, (loc, sp, m)):
                    res.append((format_action(PICKUP, (loc, sp, m)), nxt))
            # Tighten any loose nut at this location with any spanner we carry.
            sp = carrying.get(m)
            if sp is not None and ("useable", sp) in s:
                for f in s:
                    if len(f) == 3 and f[0] == "at" and f[2] == loc and f[1] in nuts:
                        nut = f[1]
                        if ("loose", nut) not in s:
                            continue
                        nxt = applicable_and_effect(s, TIGHTEN,
                                                    (loc, sp, m, nut))
                        if nxt is not None and type_check(TIGHTEN,
                                                          (loc, sp, m, nut)):
                            res.append((format_action(TIGHTEN,
                                                      (loc, sp, m, nut)), nxt))
        return res

    def _link_pairs(s, loc):
        for f in s:
            if len(f) == 3 and f[0] == "link" and f[1] == loc:
                yield (f[1], f[2])

    def goal_reached(s):
        return goal_set.issubset(s)

    if goal_reached(state):
        return []

    # BFS over frozenset state keys with a soft cap to avoid runaway expansion.
    start_key = frozenset(state)
    seen = {start_key: (None, None)}
    queue = deque([start_key])
    expanded = 0
    found = None
    while queue and expanded < SOFT_BFS_NODES:
        cur = queue.popleft()
        expanded += 1
        for act, nxt_set in successors(set(cur)):
            key = frozenset(nxt_set)
            if key in seen:
                continue
            seen[key] = (cur, act)
            if goal_reached(nxt_set):
                found = key
                break
            queue.append(key)
        if found is not None:
            break

    if found is not None:
        plan = []
        node = found
        while seen[node][0] is not None:
            _, a = seen[node]
            plan.append(a)
            node = seen[node][0]
        plan.reverse()
        if len(plan) <= MAX_STEPS and goal_reached(set(found)):
            return plan

    # Fallback: greedy improvement search (bounded).
    return _greedy(state, goal_set, men, nuts, spanners, locations,
                   applicable_and_effect, format_action, type_check,
                   successors, goal_reached)


def _greedy(state, goal_set, men, nuts, spanners, locations,
            applicable_and_effect, format_action, type_check,
            successors, goal_reached):
    cur = set(state)
    plan = []
    visited_states = set()
    for _ in range(MAX_STEPS):
        if goal_reached(cur):
            return plan
        key = frozenset(cur)
        visited_states.add(key)
        best = None
        for act, nxt in successors(cur):
            if frozenset(nxt) in visited_states:
                continue
            gained = len(goal_set & nxt) - len(goal_set & cur)
            rem = -len(goal_set - nxt)
            score = (gained, rem, -len(plan))
            if best is None or score > best[0]:
                best = (score, act, nxt)
        if best is None or best[0][0] <= 0:
            return []
        _, act, nxt = best
        plan.append(act)
        cur = nxt
    return plan if goal_reached(cur) else []
