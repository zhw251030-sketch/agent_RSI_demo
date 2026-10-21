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
"""

MAX_STEPS = 1000


def _norm(fact):
    """Normalise a predicate into a plain tuple of str."""
    if isinstance(fact, str):
        return (fact,)
    return tuple(str(part) for part in fact)


def _as_set(facts):
    out = set()
    for f in facts:
        out.add(_norm(f))
    return out


def _read_type(typ):
    """Return the declared type name of an object entry as a plain string."""
    if isinstance(typ, (list, tuple)):
        parts = [str(p) for p in typ]
        for p in parts:
            if p in ("location", "man", "nut", "spanner"):
                return p
        return parts[0] if parts else ""
    return str(typ)


def _collect(objects):
    """Return (men, nuts, spanners, locations) inferred from the type table."""
    by_type = {}
    for entry in objects:
        if isinstance(entry, (list, tuple)) and len(entry) >= 2:
            name, typ = entry[0], entry[1]
        else:
            name, typ = entry, ""
        name = str(name)
        by_type.setdefault(_read_type(typ), set()).add(name)
    return (
        set(by_type.get("man", ())),
        set(by_type.get("nut", ())),
        set(by_type.get("spanner", ())),
        set(by_type.get("location", ())),
    )


def _infer(state, goal, men, nuts, spanners, locations):
    """Widen the type sets using every argument mentioned in the predicates."""
    facts = state | goal
    for f in facts:
        head = f[0]
        args = f[1:]
        if head == "at" and len(args) == 2:
            if args[1] in locations:
                men.add(args[0])
            else:
                spanners.add(args[0])
                nuts.add(args[0])
                locations.add(args[1])
        elif head == "carrying" and len(args) == 2:
            men.add(args[0])
            spanners.add(args[1])
        elif head == "useable" and args:
            spanners.add(args[0])
        elif head in ("loose", "tightened") and args:
            nuts.add(args[0])
        elif head == "link" and len(args) == 2:
            locations.add(args[0])
            locations.add(args[1])
    for f in facts:
        for a in f[1:]:
            locations.add(a)
    return men, nuts, spanners, locations


def get_plan(objects, init, goal):
    """Return a list of grounded action strings achieving `goal` from `init`."""
    men, nuts, spanners, locations = _collect(objects)
    state = _as_set(init)
    goal_set = _as_set(goal)
    men, nuts, spanners, locations = _infer(state, goal_set, men, nuts, spanners,
                                             locations)

    links = {}
    for f in state:
        if len(f) == 3 and f[0] == "link":
            links.setdefault(f[1], set()).add(f[2])

    if goal_set.issubset(state):
        return []

    plan = _solve(state, goal_set, men, nuts, spanners, links)
    if plan is None:
        return []
    return plan[:MAX_STEPS]


def _solve(state, goal_set, men, nuts, spanners, links):
    """Construct a plan by serving each still-loose goal nut in turn."""
    nuts_to_tighten = [n for n in sorted(nuts) if ("tightened", n) in goal_set]
    nuts_to_tighten += [f[1] for f in sorted(goal_set)
                        if len(f) == 2 and f[0] == "tightened" and f[1] not in nuts]

    st = set(state)
    man = None
    at_man = sorted(f for f in st if len(f) == 3 and f[0] == "at" and f[1] in men)
    if not at_man:
        return None
    man = at_man[0][1]

    available = {s for s in spanners if ("useable", s) in st}
    co_located = {}
    for f in st:
        if len(f) == 3 and f[0] == "at" and f[1] in spanners:
            co_located.setdefault(f[2], set()).add(f[1])

    def at_m(loc):
        return ("at", man, loc) in st

    def walk_to(src, dst):
        if src == dst:
            return
        st.discard(("at", man, src))
        st.add(("at", man, dst))

    def shortest_walk(src, dst):
        if src == dst:
            return []
        seen = {src}
        frontier = [src]
        while frontier:
            nxt = []
            for loc in frontier:
                for nb in sorted(links.get(loc, ())):
                    if nb == dst:
                        return None if False else None or True and _path_via(loc, dst, src)
                    if nb in seen:
                        continue
                    seen.add(nb)
                    nxt.append(nb)
            frontier = nxt
        return None

    def _path_via(prev, goal_loc, start):
        seq = [goal_loc, prev]
        while seq[-1] != start:
            seq.append(None)
        return None

    def route(src, dst):
        """Return the intermediate locations walked through from src to dst."""
        if src == dst:
            return []
        prev = {src: None}
        frontier = [src]
        while frontier:
            nxt = []
            for loc in frontier:
                for nb in sorted(links.get(loc, ())):
                    if nb in prev:
                        continue
                    prev[nb] = loc
                    if nb == dst:
                        seq = [dst]
                        while seq[-1] != src:
                            seq.append(prev[seq[-1]])
                        seq.reverse()
                        return seq[1:]
                    nxt.append(nb)
            frontier = nxt
        return None

    plan = []
    cur_loc = None
    for f in sorted(st):
        if len(f) == 3 and f[0] == "at" and f[1] == man:
            cur_loc = f[2]
            break

    for nut in nuts_to_tighten:
        if ("tightened", nut) in st:
            continue
        nut_loc = None
        for f in st:
            if len(f) == 3 and f[0] == "at" and f[1] == nut:
                nut_loc = f[2]
                break
        if nut_loc is None:
            return None
        seq = route(cur_loc, nut_loc)
        if seq is None:
            return None
        for hop in seq:
            plan.append("(walk %s %s %s)" % (cur_loc, hop, man))
            walk_to(cur_loc, hop)
            cur_loc = hop
        # choose a usable spanner, preferring one already carried or co-located
        carried = None
        for f in st:
            if len(f) == 3 and f[0] == "carrying" and f[1] == man:
                carried = f[2]
                break
        candidates = []
        if carried is not None and carried in available:
            candidates.append(carried)
        for sp in sorted(co_located.get(nut_loc, ())):
            if sp in available and sp not in candidates:
                candidates.append(sp)
        sp = None
        sp_origin = None
        for cand in candidates:
            if ("carrying", man, cand) in st:
                sp = cand
                sp_origin = nut_loc
                break
        if sp is None:
            for cand in candidates:
                here = None
                for f in st:
                    if len(f) == 3 and f[0] == "at" and f[1] == cand:
                        here = f[2]
                        break
                if here is None:
                    continue
                sseq = route(cur_loc, here)
                if sseq is None:
                    continue
                for hop in sseq:
                    plan.append("(walk %s %s %s)" % (cur_loc, hop, man))
                    walk_to(cur_loc, hop)
                    cur_loc = hop
                plan.append("(pickup_spanner %s %s %s)" % (cur_loc, cand, man))
                st.discard(("at", cand, cur_loc))
                st.add(("carrying", man, cand))
                sp = cand
                sp_origin = cur_loc
                break
        if sp is None:
            return None
        # if the spanner was carried from elsewhere, return to the nut first
        if sp_origin != nut_loc:
            back = route(cur_loc, nut_loc)
            if back is None:
                return None
            for hop in back:
                plan.append("(walk %s %s %s)" % (cur_loc, hop, man))
                walk_to(cur_loc, hop)
                cur_loc = hop
        if ("loose", nut) not in st:
            return None
        plan.append("(tighten_nut %s %s %s %s)" % (cur_loc, sp, man, nut))
        st.discard(("loose", nut))
        st.discard(("useable", sp))
        st.add(("tightened", nut))
        available.discard(sp)

    if not goal_set.issubset(st):
        return None
    return plan
