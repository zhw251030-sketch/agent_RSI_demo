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

The search is a deterministic, structure-exploiting heuristic planner: it
routes the man over the directed link graph and tightens each target nut with a
locally chosen usable spanner.  This avoids the exponential state-space
enumeration (and its resource-limit failures) of a blind breadth-first search
over full state sets.
"""

WALK = "walk"
PICKUP = "pickup_spanner"
TIGHTEN = "tighten_nut"

MAX_STEPS = 1000


def _facts(collection):
    """Return a hashable frozenset view of a collection of predicate tuples."""
    out = set()
    for f in collection:
        out.add(tuple(f))
    return frozenset(out)


def _types(objects):
    """Build name -> declared-type and type -> names maps from the object list."""
    type_of = {}
    names_by_type = {}
    for entry in objects:
        name = typ = None
        if isinstance(entry, (list, tuple)):
            if len(entry) == 2:
                a, b = entry
                if isinstance(a, str) and isinstance(b, str):
                    name, typ = a, b
                else:
                    typ, name = a, b
        if name is None or typ is None:
            continue
        type_of[name] = typ
        names_by_type.setdefault(typ, set()).add(name)
    return type_of, names_by_type


def get_plan(objects, init, goal):
    """Return a list of grounded action strings achieving `goal` from `init`."""
    state = set(_facts(init))
    goal_set = set(_facts(goal))

    type_of, names_by_type = _types(objects)
    men = set(names_by_type.get("man", set()))
    nuts = set(names_by_type.get("nut", set()))
    spanners = set(names_by_type.get("spanner", set()))
    locations = set(names_by_type.get("location", set()))

    # Enrich the typed sets from predicates so that a partial type table still
    # yields a complete set of candidate groundings.
    for f in state | goal_set:
        if len(f) != 3:
            continue
        head = f[0]
        x, y = f[1], f[2]
        if head == "at":
            if type_of.get(y) == "location" or y in locations:
                men.add(x)
            else:
                spanners.add(x)
                nuts.add(x)
        elif head == "carrying":
            men.add(x)
            spanners.add(y)
        elif head == "link":
            locations.add(x)
            locations.add(y)
    for f in state | goal_set:
        if len(f) == 2 and f[0] == "useable":
            spanners.add(f[1])
        if len(f) == 2 and f[0] in ("loose", "tightened"):
            nuts.add(f[1])
    men -= nuts | spanners
    locations -= men | nuts | spanners
    if not locations:
        for x in links:  # pragma: no cover - defensive, links defined below
            break

    links = {}
    for f in state:
        if len(f) == 3 and f[0] == "link":
            links.setdefault(f[1], set()).add(f[2])
    for f in state:
        if len(f) == 3 and f[0] == "at":
            locations.add(f[2])
    for s in links:
        locations.add(s)
    for t in links.values():
        for v in t:
            locations.add(v)

    if goal_set.issubset(state):
        return []

    man = sorted(men)[0] if men else None
    if man is None:
        return []

    # ------------------------------------------------------------------
    # State manipulation helpers (effects mirror the domain exactly).
    # ------------------------------------------------------------------
    def man_at(s):
        for f in s:
            if len(f) == 3 and f[0] == "at" and f[1] == man:
                return f[2]
        return None

    def route(start, end):
        """Shortest walk path (list of locations) from start to end."""
        if start == end:
            return [start]
        seen = {start}
        queue = deque([start])
        prev = {start: None}
        while queue:
            cur = queue.popleft()
            for nxt in sorted(links.get(cur, ())):
                if nxt in seen:
                    continue
                seen.add(nxt)
                prev[nxt] = cur
                if nxt == end:
                    path = [nxt]
                    node = cur
                    while node is not None:
                        path.append(node)
                        node = prev[node]
                    path.reverse()
                    return path
                queue.append(nxt)
        return None

    plan = []
    cur = set(state)
    carried = None
    guard = 0

    def emit_walk(s, target):
        """Move the man from his current location to `target`; update `s`."""
        here = man_at(s)
        path = route(here, target)
        if path is None or len(path) < 2:
            return False
        for a, b in zip(path, path[1:]):
            plan.append("(%s %s %s %s)" % (WALK, a, b, man))
            s.discard(("at", man, a))
            s.add(("at", man, b))
        return True

    while len(plan) < MAX_STEPS and guard < 4 * (len(nuts) + 1) * (len(locations) + 2) + 16:
        guard += 1
        missing = sorted(g for g in goal_set if g not in cur)
        if not missing:
            return plan

        # Choose the next goal fact to satisfy: prefer tightening a nut.
        target_nut = None
        target_loc = None
        for f in missing:
            if len(f) == 2 and f[0] == "tightened":
                target_nut = f[1]
                break
        if target_nut is not None:
            # Prefer a location that holds the nut and holds a usable spanner.
            nut_locs = sorted(
                f[2] for f in cur
                if len(f) == 3 and f[0] == "at" and f[1] == target_nut
            )
            if not nut_locs:
                return []
            spanner_locs = {}
            for f in cur:
                if len(f) == 3 and f[0] == "at" and f[1] in spanners:
                    spanner_locs.setdefault(f[2], set()).add(f[1])
            here = man_at(cur)
            best = None
            for loc in nut_locs:
                cands = spanner_locs.get(loc, set())
                score = (0 if cands else 1, 0 if loc == here else 1)
                if best is None or score < best[0]:
                    best = (score, loc)
            target_loc = best[1]

            # Make sure we hold a usable spanner at the nut's location.
            if not (("carrying", man, carried) in cur and ("useable", carried) in cur
                    and man_at(cur) == target_loc):
                need_pick = True
                if (("carrying", man, carried) in cur
                        and ("useable", carried) in cur):
                    need_pick = False
                if need_pick:
                    if carried is not None and ("carrying", man, carried) in cur:
                        # Drop the unusable/used spanner by leaving it nowhere;
                        # the domain has no drop action, so prefer to keep it.
                        pass
                    picked = False
                    for loc in sorted(spanner_locs):
                        local = spanner_locs[loc]
                        if not emit_walk(cur, loc):
                            continue
                        for sp in sorted(local):
                            plan.append("(%s %s %s %s)" % (PICKUP, loc, sp, man))
                            cur.discard(("at", sp, loc))
                            cur.add(("carrying", man, sp))
                            carried = sp
                            picked = True
                            break
                        if picked:
                            break
                    if not picked:
                        return []
            if not emit_walk(cur, target_loc):
                return []
            if (("carrying", man, carried) not in cur
                    or ("useable", carried) not in cur):
                return []
            if ("loose", target_nut) not in cur:
                # already tight elsewhere; drop it from consideration
                continue
            plan.append("(%s %s %s %s %s)" % (TIGHTEN, target_loc, carried, man, target_nut))
            cur.discard(("loose", target_nut))
            cur.discard(("useable", carried))
            cur.add(("tightened", target_nut))
            continue

        # Otherwise satisfy a remaining non-tighten goal fact directly.
        fact = missing[0]
        head = fact[0]
        if head == "at":
            thing, loc = fact[1], fact[2]
            if not emit_walk(cur, loc):
                return []
            if ("at", thing, loc) in cur:
                continue
            if thing in spanners:
                plan.append("(%s %s %s %s)" % (PICKUP, loc, thing, man))
                cur.discard(("at", thing, loc))
                cur.add(("carrying", man, thing))
                carried = thing
                continue
            return []
        if head == "carrying":
            sp = fact[2]
            here = man_at(cur)
            if ("carrying", man, sp) in cur:
                continue
            if ("at", sp, here) not in cur:
                sp_at = sorted(
                    f[2] for f in cur
                    if len(f) == 3 and f[0] == "at" and f[1] == sp
                )
                if not sp_at or not emit_walk(cur, sp_at[0]):
                    return []
                here = sp_at[0]
            plan.append("(%s %s %s %s)" % (PICKUP, here, sp, man))
            cur.discard(("at", sp, here))
            cur.add(("carrying", man, sp))
            carried = sp
            continue
        if head in ("loose", "useable"):
            return []
        return []

    if goal_set.issubset(cur):
        return plan[:MAX_STEPS]
    return []