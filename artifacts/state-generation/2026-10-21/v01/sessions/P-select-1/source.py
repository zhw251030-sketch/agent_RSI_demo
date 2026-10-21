"""Spanner domain planner.

Public planning contract:
    get_plan(objects, init, goal) -> list[str]

Inputs are sets of tuples. Output is a list of at most 1000 grounded
action strings, each parenthesized.
"""

from collections import deque


# Action schemas. The order in the parameter list defines the printed
# argument order for the grounded action string.
ACTIONS = (
    ("walk", ("start", "end", "m")),
    ("pickup_spanner", ("l", "s", "m")),
    ("tighten_nut", ("l", "s", "m", "n")),
)


def _to_set(state):
    """Ensure the state is a mutable set of tuples."""
    if isinstance(state, (set, frozenset)):
        return set(state)
    return set(tuple(x) for x in state)


def _objects_by_type(objects):
    """Group object names by their declared type."""
    by_type = {}
    for name, typ in objects:
        by_type.setdefault(typ, []).append(name)
    return by_type


def _apply(effects, state):
    """Apply ADD / DEL effects of a single action to the state."""
    new_state = set(state)
    for atom in effects.get("del", ()):
        new_state.discard(atom)
    for atom in effects.get("add", ()):
        new_state.add(atom)
    return new_state


def _facts_match(state, pattern):
    """Yield all bindings under which the AND-of-literals pattern holds."""
    # pattern: list of (sign, predicate, args) where sign is + or -.
    # We evaluate negative literals by checking absence in state.
    if not pattern:
        yield {}
        return

    sign, pred, args = pattern[0]
    candidates = None
    for arg_index, arg in enumerate(args):
        if arg is None:
            continue
    # We need to enumerate substitutions. Use a backtracking approach.
    yield from _match_recursive(pattern, 0, {}, state)


def _match_recursive(pattern, idx, binding, state):
    if idx == len(pattern):
        yield dict(binding)
        return
    sign, pred, args = pattern[idx]
    # Build the set of possible grounded atoms.
    for grounded in _enumerate_atoms(pred, args, binding, state):
        if sign == "+":
            if grounded not in state:
                continue
        else:  # sign == "-"
            if grounded in state:
                continue
        # Commit binding for this atom.
        new_bindings = _extract_new_bindings(grounded, pred, args, binding)
        if new_bindings is None:
            continue
        merged = dict(binding)
        merged.update(new_bindings)
        yield from _match_recursive(pattern, idx + 1, merged, state)


def _enumerate_atoms(pred, args, binding, state):
    """Enumerate candidate atoms for a predicate, honoring current binding."""
    # Determine type of each argument position using the objects list stored
    # on state? We don't have types here. Instead, use predicate arity and the
    # set of constants present in the state.
    arity = len(args)
    # Collect possible values for each slot.
    possible = []
    for i, arg in enumerate(args):
        if arg is not None:
            possible.append([arg])
        else:
            slot_index = i
            vals = _slot_values(pred, slot_index, binding, state)
            if not vals:
                return
            possible.append(vals)
    # Cartesian product.
    from itertools import product
    for combo in product(*possible):
        yield (pred,) + combo


# Map each predicate argument position to a set of candidate object names
# drawn from the state. Because we don't have type information here, we
# use the set of constants appearing in the state for that predicate.
_PREDICATE_CONSTANTS = {}


def _slot_values(pred, slot_index, binding, state):
    # Look at all atoms with this predicate and collect constants at the slot.
    vals = set()
    for atom in state:
        if not isinstance(atom, tuple) or not atom:
            continue
        if atom[0] != pred:
            continue
        if slot_index + 1 >= len(atom):
            continue
        val = atom[slot_index + 1]
        # If this position is already bound in another atom of the same
        # pattern, it must be consistent.
        if val in binding.values():
            # Check it's not conflicting.
            if not any(binding[k] == val for k in binding):
                continue
        vals.add(val)
    return vals


def _extract_new_bindings(atom, pred, args, binding):
    """Bind variable positions in `args` to constants in `atom`."""
    new = {}
    for i, arg in enumerate(args):
        if arg is None:
            const = atom[i + 1]
            for k, v in binding.items():
                if k == arg:
                    if v != const:
                        return None
            if arg in new and new[arg] != const:
                return None
            new[arg] = const
    return new


# Better approach: rewrite planner using explicit type-based grounding.
# Replace the above with a cleaner implementation.


_TYPE_CACHE = {}


def _group_objects(objects):
    """Map type name -> list of object names."""
    by_type = {}
    for name, typ in objects:
        by_type.setdefault(typ, []).append(name)
    return by_type


# Predicate signatures: (arg_types...) — types ordered by argument position.
_PRED_TYPES = {
    "at": ("locatable", "location"),
    "carrying": ("man", "spanner"),
    "useable": ("spanner",),
    "link": ("location", "location"),
    "tightened": ("nut",),
    "loose": ("nut",),
}


def _constants_of_type(by_type, typ, state=None, pred=None, slot=None):
    """Return object names of a given type. Optionally restricted to those
    that appear in `state` under predicate `pred` at argument slot `slot`."""
    if state is not None and pred is not None and slot is not None:
        out = set()
        for atom in state:
            if not isinstance(atom, tuple) or not atom:
                continue
            if atom[0] != pred or slot + 1 >= len(atom):
                continue
            out.add(atom[slot + 1])
        return out
    return list(by_type.get(typ, ()))


def _ground_actions(by_type, state):
    """Yield (action_name, args_tuple, precond_pattern, add_set, del_set)."""
    out = []
    locs = by_type.get("location", [])
    men = by_type.get("man", [])
    spanners = by_type.get("spanner", [])
    nuts = by_type.get("nut", [])
    locatables = (by_type.get("locatable", [])
                  + men + spanners + nuts)

    # walk(?start, ?end, ?m)
    for m in men:
        for s in locs:
            for e in locs:
                if s == e:
                    continue
                out.append((
                    "walk",
                    (s, e, m),
                    [("+", "at", (m, s)), ("+", "link", (s, e))],
                    [("at", m, e)],
                    [("at", m, s)],
                ))

    # pickup_spanner(?l, ?s, ?m)
    for m in men:
        for l in locs:
            for s in spanners:
                out.append((
                    "pickup_spanner",
                    (l, s, m),
                    [("+", "at", (m, l)), ("+", "at", (s, l))],
                    [("carrying", m, s)],
                    [("at", s, l)],
                ))

    # tighten_nut(?l, ?s, ?m, ?n)
    for m in men:
        for l in locs:
            for s in spanners:
                for n in nuts:
                    out.append((
                        "tighten_nut",
                        (l, s, m, n),
                        [
                            ("+", "at", (m, l)),
                            ("+", "at", (n, l)),
                            ("+", "carrying", (m, s)),
                            ("+", "useable", (s,)),
                            ("+", "loose", (n,)),
                        ],
                        [("tightened", n)],
                        [("loose", n), ("useable", s)],
                    ))

    return out


def _precond_holds(pattern, args, state):
    """Check whether a fully grounded precondition pattern holds in state."""
    for sign, pred, pat_args in pattern:
        atom = (pred,) + tuple(pat_args)
        if sign == "+":
            if atom not in state:
                return False
        else:
            if atom in state:
                return False
    return True


def _ground_preconds_have_any(actions, state):
    """Quick pre-filter: keep only actions whose preconds could possibly hold
    given that preconds require positive facts in state. We don't fully
    check here, only narrow the candidate set."""
    keep = []
    for name, args, pattern, add, dele in actions:
        # Every positive literal must be in state for preconditions to hold.
        ok = True
        for sign, pred, pat_args in pattern:
            atom = (pred,) + tuple(pat_args)
            if sign == "+" and atom not in state:
                ok = False
                break
        if ok:
            keep.append((name, args, pattern, add, dele))
    return keep


def get_plan(objects, init, goal):
    """Plan in the spanner domain.

    Returns a list of grounded action strings of length at most 1000.
    """
    objects = list(objects)
    init = _to_set(init)
    goal = _to_set(goal)

    by_type = _group_objects(objects)

    if goal.issubset(init):
        return []

    # BFS over states.
    all_actions = _ground_actions(by_type, init)

    # Index: state -> (action_str -> next_state). We'll do BFS without
    # hashing full states by using a visited set.
    start = frozenset(init)
    target = frozenset(goal)

    # Use BFS up to a reasonable bound; if the goal contains all nuts
    # tightened, we still need to fetch spanners along the way.
    queue = deque()
    queue.append((start, []))
    visited = {start}
    max_states = 200000
    explored = 0

    while queue:
        state, plan = queue.popleft()
        explored += 1
        if explored > max_states:
            break

        if target.issubset(state):
            return _format_plan(plan)

        candidates = _ground_preconds_have_any(all_actions, state)
        for name, args, pattern, add, dele in candidates:
            if not _precond_holds(pattern, args, state):
                continue
            new_state = set(state)
            for atom in dele:
                new_state.discard(atom)
            for atom in add:
                new_state.add(atom)
            fs = frozenset(new_state)
            if fs in visited:
                continue
            visited.add(fs)
            new_plan = plan + [(name, args)]
            if len(new_plan) > 1000:
                # We've already exceeded the action limit; stop expanding
                # this branch but keep exploring others only if shorter.
                # To be safe, just skip.
                continue
            if target.issubset(fs):
                return _format_plan(new_plan)
            queue.append((fs, new_plan))

    return []


def _format_plan(plan):
    out = []
    for name, args in plan:
        out.append("(" + name + " " + " ".join(args) + ")")
    return out
