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

Repair notes
------------
The previous revision failed with `object_type` at action index 0 and, on two
tasks, exhausted the sandbox (unbounded BFS over a large state space).  Both
symptoms have the same family of likely causes that this revision removes:

* Argument objects were built from loosely typed names, so the very first
  emitted action could bind an object of the wrong declared type.  Now every
  action argument is bound only from objects whose declared type matches the
  corresponding parameter type, and objects are only ever used where the type
  table (or a consistent inference from facts) supports them.
* Search was an exhaustive breadth-first search that could explode.  It is
  replaced by a bounded, deterministic constructive planner that never
  enumerates more than a small, fixed number of candidate moves per nut, so
  runtime and memory stay small regardless of instance size.

The observation is limited to the recorded tasks: a plan was rejected at the
first action, and two tasks hit a resource limit.  The repair addresses the
plausible causes; it does not establish that these were the only causes, nor
does it guarantee success on any unseen instance.
"""

MAX_STEPS = 1000

WALK = "walk"
PICKUP = "pickup_spanner"
TIGHTEN = "tighten_nut"

# Types declared by the domain, mapped onto the parameter type each one may
# legally bind.  Anything else is never used to ground an action.
_LOCATABLE_TYPES = ("man", "nut", "spanner")


def _facts(collection):
    """Return a set of hashable predicate tuples from `collection`."""
    out = set()
    for f in collection:
        out.add(tuple(f))
    return out


def _collect_types(objects, state, goal):
    """Infer the declared type of every object name.

    `objects` provides (name, declared_type) pairs.  The declared type always
    wins; names that are only mentioned inside facts are left untyped so that
    they can never be bound to an action parameter of an unexpected type.
    """
    types = {}
    for pair in objects:
        try:
            name, declared = pair[0], pair[1]
        except (TypeError, IndexError):
            continue
        if isinstance(declared, (list, tuple)):
            # Tolerate the reversed (type, name) ordering.
            name, declared = declared, pair[0]
        if isinstance(declared, (list, tuple)):
            declared = declared[0] if declared else ""
        types.setdefault(name, str(declared))
    return types


def _facts_types(types, state):
    """Fill in types that the object table omitted, using the domain shapes."""
    for f in state:
        head = f[0]
        args = f[1:]
        if head == "link" and len(args) == 2:
            for a in args:
                types.setdefault(a, "location")
        elif head == "at" and len(args) == 2:
            subject, place = args
            types.setdefault(place, "location")
            if subject in types and types[subject] not in _LOCATABLE_TYPES:
                del types[subject]
            types.setdefault(subject, "locatable_unknown")
        elif head == "useable" and args:
            types.setdefault(args[0], "spanner")
        elif head in ("loose", "tightened") and args:
            types.setdefault(args[0], "nut")
    return types


def _location_of(types, state, name):
    """Return the location a locatable currently occupies, if any."""
    for f in state:
        if f[0] == "at" and len(f) == 3 and f[1] == name:
            return f[2]
    return None


def _walk_path(start, end, adj):
    """Return the shortest node path from `start` to `end`, or None."""
    if start == end:
        return [start]
    from collections import deque

    prev = {start: None}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        for nxt in sorted(adj.get(cur, ())):
            if nxt in prev:
                continue
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


def _fmt(name, args):
    return "(" + name + " " + " ".join(args) + ")"


def get_plan(objects, init, goal):
    """Return a list of grounded action strings achieving `goal` from `init`."""
    state = _facts(init)
    goal_set = _facts(goal)
    types = _collect_types(objects, state, goal_set)
    types = _facts_types(types, state)

    men = sorted(n for n, t in types.items() if t == "man")
    nuts = sorted(n for n, t in types.items() if t == "nut")
    spanners = sorted(n for n, t in types.items() if t == "spanner")
    locations = sorted(n for n, t in types.items() if t == "location")

    adj = {}
    for f in sorted(state):
        if f[0] == "link" and len(f) == 3:
            if f[1] in locations and f[2] in locations:
                adj.setdefault(f[1], set()).add(f[2])

    def apply_walk(st, start, end, m):
        if ("at", m, start) not in st or ("link", start, end) not in st:
            return None
        nxt = set(st)
        nxt.discard(("at", m, start))
        nxt.add(("at", m, end))
        return nxt

    def apply_pickup(st, loc, sp, m):
        if ("at", m, loc) not in st or ("at", sp, loc) not in st:
            return None
        if ("carrying", m, sp) in st:
            return None
        nxt = set(st)
        nxt.discard(("at", sp, loc))
        nxt.add(("carrying", m, sp))
        return nxt

    def apply_tighten(st, loc, sp, m, nut):
        if ("at", m, loc) not in st:
            return None
        if ("at", nut, loc) not in st:
            return None
        if ("carrying", m, sp) not in st:
            return None
        if ("useable", sp) not in st:
            return None
        if ("loose", nut) not in st:
            return None
        nxt = set(st)
        nxt.discard(("loose", nut))
        nxt.discard(("useable", sp))
        nxt.add(("tightened", nut))
        return nxt

    plan = []

    def extend(to, m):
        """Walk man `m` from its current location to location `to`."""
        cur = _location_of(types, state, m)
        if cur is None or cur == to:
            return True
        path = _walk_path(cur, to, adj)
        if path is None:
            return False
        for i in range(len(path) - 1):
            nxt = apply_walk(state, path[i], path[i + 1], m)
            if nxt is None:
                return False
            state.clear()
            state.update(nxt)
            plan.append(_fmt(WALK, [path[i], path[i + 1], m]))
            if len(plan) >= MAX_STEPS:
                return False
        return True

    # Loose nuts that must be tightened, in a deterministic order.
    pending = [n for n in nuts if ("loose", n) in state and ("tightened", n) in goal_set]
    for nut in pending:
        nut_loc = _location_of(types, state, nut)
        if nut_loc is None:
            return []
        done = False
        for m in men:
            if len(plan) >= MAX_STEPS:
                return []
            # Candidate spanner: carried by m, or co-located with m.
            if not extend(nut_loc, m):
                continue
            here = [sp for sp in spanners
                    if ("useable", sp) in state
                    and (("carrying", m, sp) in state or ("at", sp, nut_loc) in state)]
            for sp in here:
                if ("carrying", m, sp) not in state:
                    nxt = apply_pickup(state, nut_loc, sp, m)
                    if nxt is None:
                        continue
                    state.clear()
                    state.update(nxt)
                    plan.append(_fmt(PICKUP, [nut_loc, sp, m]))
                nxt = apply_tighten(state, nut_loc, sp, m, nut)
                if nxt is None:
                    continue
                state.clear()
                state.update(nxt)
                plan.append(_fmt(TIGHTEN, [nut_loc, sp, m, nut]))
                done = True
                break
            if done:
                break
        if not done:
            return []

    if not goal_set.issubset(state):
        return []
    return plan[:MAX_STEPS]