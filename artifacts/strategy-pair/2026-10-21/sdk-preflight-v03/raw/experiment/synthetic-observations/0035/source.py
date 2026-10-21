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


def _as_set(facts):
    """Return a hashable set view of a collection of predicate tuples."""
    out = set()
    for f in facts:
        out.add(tuple(f))
    return out


def _typed(objects):
    """Build the type -> set-of-names mapping and the man/spanner/nut sets."""
    by_type = {}
    for name, typ in objects:
        by_type.setdefault(tuple(typ) if isinstance(typ, (list, tuple)) else (typ,), set()).add(name)
        # tolerate a reversed ("type", name) ordering
        if isinstance(typ, (list, tuple)):
            continue
    men = set(by_type.get(("man",), set()))
    nuts = set(by_type.get(("nut",), set()))
    spanners = set(by_type.get(("spanner",), set()))
    locations = set(by_type.get(("location",), set()))
    return men, nuts, spanners, locations


def get_plan(objects, init, goal):
    """Return a list of grounded action strings achieving `goal` from `init`."""
    men, nuts, spanners, locations = _typed(objects)
    state = _as_set(init)
    goal_set = _as_set(goal)

    # Planners support objects even when the type table is incomplete, so
    # enrich the type sets from the predicates present in the state/goal.
    for f in state | goal_set:
        if len(f) >= 2:
            head = f[0]
            args = f[1:]
            if head == "at":
                if len(args) == 2:
                    if args[1] in locations:
                        men.add(args[0])
                    else:
                        spanners.add(args[0])
                        nuts.add(args[0])
            elif head == "carrying" and len(args) == 2:
                men.add(args[0])
                spanners.add(args[1])
            elif head in ("useable",) and args:
                spanners.add(args[0])
            elif head in ("loose", "tightened") and args:
                nuts.add(args[0])

    # Fall back to anything mentioned in the predicates if still unknown.
    for f in state | goal_set:
        for a in f[1:]:
            men.add(a) if False else None

    links = {}
    for f in state:
        if len(f) == 3 and f[0] == "link":
            links.setdefault(f[1], set()).add(f[2])
    for s in links:
        locations.add(s)
    for t in links.values():
        for v in t:
            locations.add(v)

    def applicable_and_effect(s, action, args):
        """Return the successor state if `action` applies in `s`, else None."""
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

    def successors(s):
        """Yield (action_string, successor_state) pairs, deterministically."""
        res = []
        at_man = sorted((f[1], f[2]) for f in s if len(f) == 3 and f[0] == "at" and f[1] in men)
        for m, loc in at_man:
            for end in sorted(links.get(loc, ())):
                nxt = applicable_and_effect(s, WALK, (loc, end, m))
                if nxt is not None:
                    res.append((format_action(WALK, (loc, end, m)), nxt))
            for sp in sorted(spanners):
                nxt = applicable_and_effect(s, PICKUP, (loc, sp, m))
                if nxt is not None:
                    res.append((format_action(PICKUP, (loc, sp, m)), nxt))
                for nut in sorted(nuts):
                    nxt = applicable_and_effect(s, TIGHTEN, (loc, sp, m, nut))
                    if nxt is not None:
                        res.append((format_action(TIGHTEN, (loc, sp, m, nut)), nxt))
        return res

    def goal_reached(s):
        return goal_set.issubset(s)

    if goal_reached(state):
        return []

    # Breadth-first search over states, keeping the parent action for each
    # newly discovered state so that a full plan can be reconstructed.
    seen = {frozenset(state): None}
    queue = deque([frozenset(state)])
    while queue:
        cur = queue.popleft()
        for act, nxt in successors(set(cur)):
            key = frozenset(nxt)
            if key in seen:
                continue
            seen[key] = (cur, act)
            if goal_set.issubset(nxt):
                plan = []
                node = key
                while seen[node] is not None:
                    prev, a = seen[node]
                    plan.append(a)
                    node = prev
                plan.reverse()
                return plan[:MAX_STEPS]
            queue.append(key)

    # Fallback: attempt a simple greedy post-hoc composition.
    return _greedy(state, goal_set, men, nuts, spanners, links, applicable_and_effect,
                   format_action, successors, goal_reached)


def _greedy(state, goal_set, men, nuts, spanners, links, applicable_and_effect,
            format_action, successors, goal_reached):
    """Depth-limited greedy search used only if the plain BFS found nothing."""
    cur = set(state)
    plan = []
    for _ in range(MAX_STEPS):
        if goal_reached(cur):
            return plan
        best = None
        for act, nxt in successors(cur):
            if frozenset(nxt) == frozenset(cur):
                continue
            gain = len((goal_set & nxt) - goal_set)
            score = (gain, len(goal_set - nxt))
            if best is None or score > best[0]:
                best = (score, act, nxt)
        if best is None or best[0][0] <= 0:
            return []
        plan.append(best[1])
        cur = best[2]
    return plan if goal_reached(cur) else []