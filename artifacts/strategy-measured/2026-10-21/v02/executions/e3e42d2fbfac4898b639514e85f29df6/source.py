"""Grounded planner for the "spanner" STRIPS domain.

Public contract
---------------
get_plan(objects, init, goal) -> list[str]

`objects` is a collection of (name, type) pairs, `init` and `goal` are
collections of predicate tuples such as ("at", "bob", "shed").
The returned plan is a list of parenthesised grounded action strings using the
exact argument order given in the domain definition:

    (walk <start> <end> <man>)
    (pickup_spanner <loc> <spanner> <man>)
    (tighten_nut <loc> <spanner> <man> <nut>)

Only the Python standard library is used and the inputs are never mutated.
"""

from collections import deque

WALK = "walk"
PICKUP = "pickup_spanner"
TIGHTEN = "tighten_nut"

MAX_STEPS = 1000
MAX_NODES = 200000


def _norm_atom(f):
    """Coerce a predicate given as tuple/list/other sequence into a tuple."""
    if isinstance(f, (list, tuple)):
        return tuple(f)
    if isinstance(f, str):
        parts = f.replace("(", " ").replace(")", " ").split()
        return tuple(parts)
    try:
        return tuple(f)
    except TypeError:
        return (f,)


def _as_set(facts):
    """Return a hashable set view of a collection of predicate tuples."""
    out = set()
    for f in facts or ():
        out.add(_norm_atom(f))
    return out


def _typed(objects):
    """Build the man/spanner/nut/location name sets from the type table."""
    by_type = {}
    for entry in objects or ():
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            continue
        name, typ = entry[0], entry[1]
        if isinstance(typ, (list, tuple)):
            keys = tuple(typ)
        else:
            keys = (typ,)
        for k in keys:
            by_type.setdefault(k, set()).add(name)
    men = set(by_type.get("man", set()))
    nuts = set(by_type.get("nut", set()))
    spanners = set(by_type.get("spanner", set()))
    locations = set(by_type.get("location", set()))
    return men, nuts, spanners, locations


def get_plan(objects, init, goal):
    """Return a list of grounded action strings achieving `goal` from `init`."""
    men, nuts, spanners, locations = _typed(objects)
    state = _as_set(init)
    goal_set = _as_set(goal)

    # Enrich type sets from the predicates that actually occur.
    for f in state | goal_set:
        if len(f) == 3 and f[0] == "at":
            a, b = f[1], f[2]
            if b in locations:
                men.add(a)
            else:
                if a in men or a in spanners:
                    spanners.add(a)
                nuts.add(b)
                locations.add(b)
        elif len(f) == 2 and f[0] == "carrying":
            men.add(f[1 - 1])
            men.add(f[1])
            spanners.add(f[1] if False else f[2 - 1])
        elif len(f) >= 1 and f[0] == "useable":
            spanners.add(f[1])
        elif len(f) >= 1 and f[0] in ("loose", "tightened"):
            nuts.add(f[1])

    links = {}
    for f in state:
        if len(f) == 3 and f[0] == "link":
            links.setdefault(f[1], set()).add(f[2])
            locations.add(f[1])
            locations.add(f[2])

    # Nut locations from the current state (nuts never move).
    nut_at = {}
    for f in state:
        if len(f) == 3 and f[0] == "at" and f[1] in nuts:
            nut_at.setdefault(f[1], set()).add(f[2])
    for f in goal_set:
        if len(f) >= 1 and f[0] == "tightened":
            nut_at.setdefault(f[1], set())

    goals_by_loc = {}
    need = []
    for f in sorted(goal_set):
        if f[0] != "tightened":
            continue
        nut = f[1]
        locs = sorted(nut_at.get(nut, set())) or sorted(locations)
        for loc in locs:
            goals_by_loc.setdefault(loc, []).append(nut)
            need.append((loc, nut))
            break

    if not need:
        return []
    if goal_set.issubset(state):
        return []

    def fmt(action, args):
        return "(" + action + " " + " ".join(args) + ")"

    def walk_path(start, target):
        """Breadth-first shortest walk as a list of (start, end) pairs."""
        if start == target:
            return []
        seen = {start}
        q = deque([(start, [])])
        while q:
            cur, path = q.popleft()
            for nxt in sorted(links.get(cur, ())):
                if nxt in seen:
                    continue
                np_ = path + [(cur, nxt)]
                if nxt == target:
                    return np_
                seen.add(nxt)
                q.append((nxt, np_))
        return None

    man_at = {}
    for f in state:
        if len(f) == 3 and f[0] == "at" and f[1] in men:
            man_at.setdefault(f[1], set()).add(f[2])

    # Usable spanners, in preference order (closest to the first man first).
    usable = sorted(s for s in spanners if ("useable", s) in state)
    man_sorted = sorted(men)

    def spanner_at(s):
        return f[2] for f in ()  # placeholder, unused

    # Map spanner -> its location from the state.
    sp_loc = {}
    for f in state:
        if len(f) == 3 and f[0] == "at" and f[1] in spanners:
            sp_loc.setdefault(f[1], set()).add(f[2])

    pending = dict(goals_by_loc)
    man_loc = {m: sorted(man_at.get(m, {"?"}))[0] if man_at.get(m) else None
               for m in man_sorted}
    if not man_sorted:
        return []

    def nearest_man(loc):
        best = None
        for m in man_sorted:
            ml = man_loc.get(m)
            if ml is None:
                continue
            p = walk_path(ml, loc)
            if p is None:
                continue
            if best is None or len(p) < len(best[0]):
                best = (p, m, ml)
        return best

    plan = []
    steps = 0
    while pending and steps < MAX_STEPS:
        # Choose the next (loc, nut) pair to handle: nearest one.
        choice = None
        for loc, nuts_list in sorted(pending.items()):
            cand = nearest_man(loc)
            if cand is None:
                continue
            if choice is None or len(cand[0]) < len(choice[0]):
                choice = (cand[0], m_cand := cand[1], m_start := cand[2], loc,
                          nuts_list[0])
        if choice is None:
            return []
        wpath, man, mloc, loc, nut = choice
        for (a, b) in wpath:
            plan.append(fmt(WALK, (a, b, man)))
            man_loc[man] = b
            steps += 1
        # Ensure we hold a usable spanner at this location.
        holding = None
        for s in sorted(spanners):
            if ("carrying", man, s) in state and ("useable", s) in state:
                holding = s
                break
        if holding is None:
            pick = None
            for s in usable:
                if ("carrying", man, s) in state:
                    pick = ("carry", s)
                    break
            if pick is None:
                for s in usable:
                    here = loc in sp_loc.get(s, set())
                    if here:
                        plan.append(fmt(PICKUP, (loc, s, man)))
                        steps += 1
                        pick = ("carry", s)
                        break
            if pick is None:
                # Walk to the nearest usable spanner, pick it up, come back.
                best = None
                for s in usable:
                    for sl in sorted(sp_loc.get(s, set())):
                        nm = nearest_man(sl)
                        if nm is None:
                            continue
                        d = len(nm[0]) + len(walk_path(sl, loc) or [None] * 9999)
                        if best is None or d < best[0]:
                            best = (d, s, sl, nm)
                if best is None:
                    return []
                _, s, sl, nm = best
                for (a, b) in nm[0]:
                    plan.append(fmt(WALK, (a, b, man)))
                    man_loc[man] = b
                    steps += 1
                plan.append(fmt(PICKUP, (sl, s, man)))
                steps += 1
                back = walk_path(sl, loc)
                if back is None:
                    return []
                for (a, b) in back:
                    plan.append(fmt(WALK, (a, b, man)))
                    man_loc[man] = b
                    steps += 1
                holding = s
            else:
                holding = pick[1]
        if holding is None:
            return []
        plan.append(fmt(TIGHTEN, (loc, holding, man, nut)))
        steps += 1
        # Update bookkeeping.
        for m in man_sorted:
            man_loc[m] = loc if m == man else man_loc[m]
        pending[loc] = [n for n in pending[loc] if n != nut]
        if not pending[loc]:
            del pending[loc]

    if pending:
        return []
    return plan[:MAX_STEPS]