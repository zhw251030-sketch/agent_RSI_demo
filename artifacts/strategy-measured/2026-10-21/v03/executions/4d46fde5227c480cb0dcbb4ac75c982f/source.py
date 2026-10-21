"""Grounded planner for the 'spanner' planning domain.

Public contract:
    get_plan(objects, init, goal) -> list[str]

`objects` is a collection of (name, type) pairs; `init` and `goal` are
collections of predicate tuples (given as arrays in JSON).  The returned plan
is a list of parenthesized grounded action strings, using exactly the argument
order given in the domain definition.

The implementation builds an explicit state-space model of the domain and
performs a breadth-first search over grounded action sequences, so every step
is checked against the real preconditions/effects of the domain definition.
"""

import collections


def _fmt(action, args):
    return "(" + " ".join([action] + [str(a) for a in args]) + ")"


class _Domain(object):
    """Grounded simulator for the spanner domain (no mutation of inputs)."""

    def __init__(self, objects, init):
        self.types = {}
        for pair in objects:
            name = pair[0]
            tname = pair[1]
            self.types.setdefault(name, set()).add(tname)

        self.init_state = set()
        for fact in init:
            self.init_state.add(tuple(fact))

        self.locations = sorted(n for n in self.types
                                if self._isa(n, "location"))
        self.nuts = sorted(n for n in self.types if self._isa(n, "nut"))
        self.spanners = sorted(n for n in self.types
                               if self._isa(n, "spanner"))
        self.men = sorted(n for n in self.types if self._isa(n, "man"))

    def _isa(self, obj, tname):
        return tname in self.types.get(obj, ())

    # ------------------------------------------------------------------
    # Action space (static): grounded from declared types only.
    # ------------------------------------------------------------------
    def actions(self):
        acts = []
        for start in self.locations:
            for end in self.locations:
                if start == end:
                    continue
                for m in self.men:
                    acts.append(("walk", (start, end, m)))
        for l in self.locations:
            for s in self.spanners:
                for m in self.men:
                    acts.append(("pickup_spanner", (l, s, m)))
        for l in self.locations:
            for s in self.spanners:
                for m in self.men:
                    for n in self.nuts:
                        acts.append(("tighten_nut", (l, s, m, n)))
        return acts

    @staticmethod
    def apply(state, name, args):
        """Return (adds, dels) for a grounded action, per the domain."""
        if name == "walk":
            start, end, m = args
            adds = [("at", m, end)]
            dels = [("at", m, start)]
        elif name == "pickup_spanner":
            l, s, m = args
            adds = [("carrying", m, s)]
            dels = [("at", s, l)]
        elif name == "tighten_nut":
            l, s, m, n = args
            adds = [("tightened", n)]
            dels = [("loose", n), ("useable", s)]
        else:
            return [], []
        return adds, dels

    @staticmethod
    def precondition_ok(state, name, args):
        if name == "walk":
            start, end, m = args
            return (("at", m, start) in state
                    and ("link", start, end) in state)
        if name == "pickup_spanner":
            l, s, m = args
            return (("at", m, l) in state and ("at", s, l) in state)
        if name == "tighten_nut":
            l, s, m, n = args
            return (("at", m, l) in state and ("at", n, l) in state
                    and ("carrying", m, s) in state
                    and ("useable", s) in state and ("loose", n) in state)
        return False

    def successor(self, state, name, args):
        adds, dels = self.apply(state, name, args)
        new = set(state)
        for f in dels:
            new.discard(f)
        for f in adds:
            new.add(f)
        return frozenset(new)


def _goal_satisfied(state, goal_facts):
    return all(f in state for f in goal_facts)


def _relaxed_reachable(state, goal_facts, dom):
    """Optimistic delete-relaxation reachability check (pruning only)."""
    relaxed = set(state)
    changed = True
    while changed:
        changed = False
        if _goal_satisfied(relaxed, goal_facts):
            return True
        for name, args in dom.actions():
            if name == "walk":
                start, end, m = args
                if (("at", m, start) in relaxed
                        and ("link", start, end) in relaxed
                        and ("at", m, end) not in relaxed):
                    relaxed.add(("at", m, end))
                    changed = True
            elif name == "pickup_spanner":
                l, s, m = args
                if (("at", m, l) in relaxed and ("at", s, l) in relaxed
                        and ("carrying", m, s) not in relaxed):
                    relaxed.add(("carrying", m, s))
                    changed = True
            else:
                l, s, m, n = args
                if (("at", m, l) in relaxed and ("at", n, l) in relaxed
                        and ("carrying", m, s) in relaxed
                        and ("useable", s) in relaxed
                        and ("loose", n) in relaxed
                        and ("tightened", n) not in relaxed):
                    relaxed.add(("tightened", n))
                    changed = True
    return _goal_satisfied(relaxed, goal_facts)


def get_plan(objects, init, goal):
    dom = _Domain(objects, init)
    goal_facts = set(tuple(g) for g in goal)
    start = frozenset(dom.init_state)

    if _goal_satisfied(start, goal_facts):
        return []

    all_actions = dom.actions()

    # Prefer goal-relevant nuts first so tighten_nut grounding is tried early.
    goal_nuts = set(f[1] for f in goal_facts
                    if f and f[0] == "tightened" and len(f) > 1)

    def sort_key(item):
        name, args = item
        if name == "tighten_nut":
            rank = 0 if (len(args) > 3 and args[3] in goal_nuts) else 2
        elif name == "pickup_spanner":
            rank = 1
        else:
            rank = 1
        return (rank, name, tuple(str(a) for a in args))

    ordered_actions = sorted(all_actions, key=sort_key)

    max_len = 1000
    limit_states = 400000

    if not _relaxed_reachable(start, goal_facts, dom):
        return []

    visited = {start}
    queue = collections.deque([(start, [])])
    expanded = 0

    while queue:
        state, plan = queue.popleft()
        if len(plan) >= max_len:
            continue
        expanded += 1
        if expanded > limit_states:
            break
        for name, args in ordered_actions:
            if not dom.precondition_ok(state, name, args):
                continue
            nxt = dom.successor(state, name, args)
            if nxt in visited:
                continue
            new_plan = plan + [_fmt(name, args)]
            if _goal_satisfied(nxt, goal_facts):
                return new_plan
            if len(new_plan) >= max_len:
                continue
            visited.add(nxt)
            queue.append((nxt, new_plan))

    return []