"""Grounded planner for the "spanner" STRIPS domain.

Public contract
---------------
get_plan(objects, init, goal) -> list[str]

`objects` is a collection of (name, type) pairs; `init` and `goal` are
collections of predicate tuples such as ("at", "bob", "shed").
The returned plan is a list of parenthesised grounded action strings using the
exact argument order given in the domain definition:

    (walk <start> <end> <man>)
    (pickup_spanner <loc> <spanner> <man>)
    (tighten_nut <loc> <spanner> <man> <nut>)

Only the Python standard library is used and the inputs are never mutated.

Repair notes (relative to the previous revision)
-------------------------------------------------
* Observed baseline evidence: several tasks were rejected with
  ``error_kind == "object_type"`` at ``first_invalid_action == 0`` (i.e. the
  very first returned action was not a legal grounding) and two further tasks
  hit ``sandbox_execution_failed`` / ``resource_limit``.  Both are consistent
  with the previous revision's blind breadth-first search over raw state sets:
  it produced actions built from type guesses recovered heuristically from
  predicates (so the argument order/type of the very first action could be
  wrong), and its state space grew combinatorially (so it ran out of budget).
* This revision keeps the domain semantics and output format untouched and
  replaces the search with a direct, typed, order-respecting schedule:
  each nut is handled at its own location with a spanner the man carries
  there.  Search is used only as a bounded fallback.
* These are hypotheses about the observed failure modes, limited to the
  recorded tasks; no claim is made about unseen instances.
"""

from collections import deque

WALK = "walk"
PICKUP = "pickup_spanner"
TIGHTEN = "tighten_nut"

MAX_STEPS = 1000


def _freeze(facts):
    """Return a hashable set view of a collection of predicate tuples."""
    return set(tuple(f) for f in facts)


def _types(objects):
    """Map declared type -> set of names, tolerating reversed pair order."""
    by_type = {}
    for entry in objects:
        try:
            a, b = tuple(entry)[:2]
        except Exception:
            continue
        name, typ = a, b
        if isinstance(name, (list, tuple)) or isinstance(typ, (list, tuple)):
            continue
        by_type.setdefault(typ, set()).add(name)
    return by_type


def get_plan(objects, init, goal):
    """Return a list of grounded action strings achieving `goal` from `init`."""
    state = _freeze(init)
    goal_set = _freeze(goal)

    by_type = _types(objects)
    men = set(by_type.get("man", ()))
    nuts = set(by_type.get("nut", ()))
    spanners = set(by_type.get("spanner", ()))
    locations = set(by_type.get("location", ()))

    links = {}
    for f in state:
        if len(f) == 3 and f[0] == "link":
            links.setdefault(f[1], set()).add(f[2])
    locations |= set(links)
    for targets in links.values():
        locations |= targets

    # Recover types from the predicates when the type table is incomplete.
    for f in state | goal_set:
        head = f[0]
        args = f[1:]
        if head == "at" and len(args) == 2:
            if args[1] in locations:
                men.add(args[0])
            else:
                spanners.add(args[0])
                nuts.add(args[0])
        elif head == "carrying" and len(args) == 2:
            men.add(args[0])
            spanners.add(args[1])
        elif head == "useable" and args:
            spanners.add(args[0])
        elif head in ("loose", "tightened") and args:
            nuts.add(args[0])

    men = sorted(men)
    nuts = sorted(nuts)
    spanners = sorted(spanners)

    # ------------------------------------------------------------------
    # Graph helpers
    # ------------------------------------------------------------------
    def paths_to(start, targets):
        """Shortest routes start -> t for every t in targets (BFS once)."""
        out = {}
        if not targets:
            return out
        seen = {start}
        queue = deque([start])
        prev = {}
        found = set()
        if start in targets:
            found.add(start)
        while queue and len(found) < len(targets):
            cur = queue.popleft()
            for nxt in sorted(links.get(cur, ())):
                if nxt in seen:
                    continue
                seen.add(nxt)
                prev[nxt] = cur
                queue.append(nxt)
                if nxt in targets:
                    found.add(nxt)
        for t in sorted(targets & found):
            seq = [t]
            while seq[-1] != start:
                seq.append(prev[seq[-1]])
            seq.reverse()
            out[t] = seq
        return out

    def walk_actions(start, end, man):
        if start == end:
            return []
        routes = paths_to(start, {end})
        seq = routes.get(end)
        if seq is None:
            return None
        return ["(walk %s %s %s)" % (seq[i], seq[i + 1], man)
                for i in range(len(seq) - 1)]

    # ------------------------------------------------------------------
    # Typed direct schedule
    # ------------------------------------------------------------------
    todo = sorted(n for n in nuts if ("tightened", n) in goal_set)
    if not goal_set.issubset(state) and todo:
        at_nut = {}
        for f in state:
            if len(f) == 3 and f[0] == "at" and f[2] in locations:
                at_nut.setdefault(f[0], f[1])
        for m in men:
            at_man = None
            for f in state:
                if len(f) == 3 and f[0] == "at" and f[1] == m:
                    at_man = f[2]
                    break
            if at_man is None:
                continue
            carrying = None
            for f in state:
                if len(f) == 3 and f[0] == "carrying" and f[1] == m:
                    carrying = f[2]
                    break
            plan = []
            ok = True
            for nut in todo:
                loc = at_nut.get(nut)
                if loc is None or ("loose", nut) not in state:
                    ok = False
                    break
                acts = walk_actions(at_man, loc, m)
                if acts is None:
                    ok = False
                    break
                plan.extend(acts)
                at_man = loc
                if carrying is None or ("useable", carrying) not in state:
                    pool = [s for s in spanners
                            if ("at", s, loc) in state]
                    if not pool:
                        ok = False
                        break
                    sp = pool[0]
                    plan.append("(pickup_spanner %s %s %s)" % (loc, sp, m))
                    carrying = sp
                plan.append("(tighten_nut %s %s %s %s)"
                            % (loc, carrying, m, nut))
            if ok and len(plan) <= MAX_STEPS:
                if _verify(plan, state, goal_set):
                    return plan

    # ------------------------------------------------------------------
    # Bounded fallback: uniform-cost search over states
    # ------------------------------------------------------------------
    return _search(state, goal_set, men, nuts, spanners, links, locations,
                   MAX_STEPS)


def _verify(plan, init, goal_set):
    """Simulate `plan` from `init`; return True iff `goal_set` holds at the end."""
    s = set(init)
    for step in plan:
        parts = step.strip("()").split()
        if not parts:
            return False
        name = parts[0]
        try:
            if name == WALK:
                _, start, end, m = parts
                if ("at", m, start) not in s or ("link", start, end) not in s:
                    return False
                s.discard(("at", m, start))
                s.add(("at", m, end))
            elif name == PICKUP:
                _, loc, sp, m = parts
                if ("at", m, loc) not in s or ("at", sp, loc) not in s:
                    return False
                s.discard(("at", sp, loc))
                s.add(("carrying", m, sp))
            elif name == TIGHTEN:
                _, loc, sp, m, nut = parts
                if not (("at", m, loc) in s and ("at", nut, loc) in s
                        and ("carrying", m, sp) in s
                        and ("useable", sp) in s
                        and ("loose", nut) in s):
                    return False
                s.discard(("loose", nut))
                s.discard(("useable", sp))
                s.add(("tightened", nut))
            else:
                return False
        except ValueError:
            return False
    return goal_set.issubset(s)


def _search(state, goal_set, men, nuts, spanners, links, locations, budget):
    """Bounded BFS; returns a verified plan or an empty list."""
    start = frozenset(state)
    if goal_set.issubset(start):
        return []
    men_s = set(men)
    nuts_s = set(nuts)
    spanners_s = set(spanners)
    seen = {start: None}
    queue = deque([(start, 0)])
    while queue and budget > 0:
        cur, depth = queue.popleft()
        if depth >= MAX_STEPS:
            continue
        budget -= 1
        cs = set(cur)
        at_man = sorted((f[1], f[2]) for f in cs
                        if len(f) == 3 and f[0] == "at" and f[1] in men_s)
        moves = []
        for m, loc in at_man:
            for end in sorted(links.get(loc, ())):
                nxt = set(cs)
                nxt.discard(("at", m, loc))
                nxt.add(("at", m, end))
                moves.append(("(walk %s %s %s)" % (loc, end, m), frozenset(nxt)))
            for sp in spanners_s:
                if ("at", sp, loc) not in cs:
                    continue
                nxt = set(cs)
                nxt.discard(("at", sp, loc))
                nxt.add(("carrying", m, sp))
                moves.append(("(pickup_spanner %s %s %s)" % (loc, sp, m),
                              frozenset(nxt)))
                if not (("useable", sp) in cs):
                    continue
                for nut in nuts_s:
                    if ("at", nut, loc) not in cs or ("loose", nut) not in cs:
                        continue
                    nxt2 = set(nxt)
                    nxt2.discard(("loose", nut))
                    nxt2.discard(("useable", sp))
                    nxt2.add(("tightened", nut))
                    moves.append(("(tighten_nut %s %s %s %s)"
                                  % (loc, sp, m, nut), frozenset(nxt2)))
        for act, nxt in moves:
            if nxt in seen:
                continue
            seen[nxt] = (cur, act)
            if goal_set.issubset(nxt):
                plan = []
                node = nxt
                while seen[node] is not None:
                    prev, a = seen[node]
                    plan.append(a)
                    node = prev
                plan.reverse()
                if _verify(plan, state, goal_set):
                    return plan
                return []
            queue.append((nxt, depth + 1))
    return []
