"""BFS planner for the spanner domain."""

from collections import deque


def get_plan(objects, init, goal):
    objects = set(objects)
    init = set(init)
    goal = set(goal)

    # Determine the man (only one man in these instances).
    men = [n for n, t in objects if t == "man"]
    if not men:
        return []
    man = men[0]

    spanners = {n for n, t in objects if t == "spanner"}
    nuts = {n for n, t in objects if t == "nut"}

    # Build location graph from init (directed links).
    links = set()
    for fact in init:
        if fact[0] == "link":
            links.add((fact[1], fact[2]))

    # BFS to find shortest directed path from src to dst over links.
    def shortest_path(src, dst):
        if src == dst:
            return [src]
        visited = {src}
        queue = deque([(src, [src])])
        while queue:
            node, path = queue.popleft()
            for a, b in links:
                if a == node and b not in visited:
                    new_path = path + [b]
                    if b == dst:
                        return new_path
                    visited.add(b)
                    queue.append((b, new_path))
        return None

    # Helper to apply an action and return a new frozenset state.
    def apply_action(state, action):
        new_state = set(state)
        if action[0] == "walk":
            _, start, end, m = action
            new_state.discard(("at", m, start))
            new_state.add(("at", m, end))
        elif action[0] == "pickup_spanner":
            _, l, s, m = action
            new_state.discard(("at", s, l))
            new_state.add(("carrying", m, s))
        elif action[0] == "tighten_nut":
            _, l, s, m, n = action
            new_state.discard(("loose", n))
            new_state.discard(("useable", s))
            new_state.add(("tightened", n))
        return frozenset(new_state)

    def is_applicable(state, action):
        if action[0] == "walk":
            _, start, end, m = action
            return ("at", m, start) in state and (start, end) in links
        if action[0] == "pickup_spanner":
            _, l, s, m = action
            return ("at", m, l) in state and ("at", s, l) in state
        if action[0] == "tighten_nut":
            _, l, s, m, n = action
            return (
                ("at", m, l) in state
                and ("at", n, l) in state
                and ("carrying", m, s) in state
                and ("useable", s) in state
                and ("loose", n) in state
            )
        return False

    # State: frozenset of init facts. We need to track a few derived views
    # during search. BFS over state space may be large; use goal-aware search.

    initial_state = frozenset(init)

    if goal.issubset(initial_state):
        return []

    # Precompute man location, carried spanners.
    def man_at(state):
        for f in state:
            if f[0] == "at" and f[1] == man:
                return f[2]
        return None

    def carrying(state):
        for f in state:
            if f[0] == "carrying" and f[1] == man:
                return f[2]
        return None

    def spanner_loc(state, s):
        for f in state:
            if f[0] == "at" and f[1] == s:
                return f[2]
        return None

    def nut_loc(state, n):
        for f in state:
            if f[0] == "at" and f[1] == n:
                return f[2]
        return None

    def nut_loose(state, n):
        return ("loose", n) in state

    def spanner_usable(state, s):
        return ("useable", s) in state

    # For each state we track: (state_facts, action_plan_or_None)
    visited = {initial_state}
    queue = deque([(initial_state, [])])

    while queue:
        state, plan = queue.popleft()
        # Generate applicable actions.
        actions = []
        mloc = man_at(state)
        if mloc is None:
            continue
        carried = carrying(state)

        # Walk actions from mloc.
        for a, b in links:
            if a == mloc:
                actions.append(("walk", a, b, man))

        # Pickup actions: at mloc, pick any spanner at mloc not yet carried.
        for s in spanners:
            if spanner_loc(state, s) == mloc:
                actions.append(("pickup_spanner", mloc, s, man))

        # Tighten actions: carrying usable spanner, at a location with a loose nut.
        if carried is not None and spanner_usable(state, carried):
            for n in nuts:
                if nut_loc(state, n) == mloc and nut_loose(state, n):
                    actions.append(("tighten_nut", mloc, carried, man, n))

        for action in actions:
            if not is_applicable(state, action):
                continue
            new_state = apply_action(state, action)
            if new_state in visited:
                continue
            new_plan = plan + [action]
            if goal.issubset(new_state):
                return [_format_action(a) for a in new_plan]
            visited.add(new_state)
            queue.append((new_state, new_plan))

    return []


def _format_action(a):
    if a[0] == "walk":
        return f"(walk {a[1]} {a[2]} {a[3]})"
    if a[0] == "pickup_spanner":
        return f"(pickup_spanner {a[1]} {a[2]} {a[3]})"
    if a[0] == "tighten_nut":
        return f"(tighten_nut {a[1]} {a[2]} {a[3]} {a[4]})"
    return str(a)