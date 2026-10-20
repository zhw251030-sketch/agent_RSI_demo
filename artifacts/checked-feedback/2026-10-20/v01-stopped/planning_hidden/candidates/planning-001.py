"""General forward-search (BFS) STRIPS planner for the spanner domain."""

def get_plan(objects, init, goal):
    # typed object sets
    by_type = {}
    for name, typ in objects:
        by_type.setdefault(typ, set()).add(name)

    def sort_names(s):
        return sorted(s)

    men = sort_names(by_type.get("man", set()))
    spanners = sort_names(by_type.get("spanner", set()))
    nuts = sort_names(by_type.get("nut", set()))
    locations = sort_names(by_type.get("location", set()))

    init = set(init)
    goal = set(goal)
    goals = goal

    # grounded action generators: each returns (action_string, add_set, del_set)
    def actions(state):
        at_man = {}
        at_sp = {}
        carrying = {}
        for f in state:
            if f[0] == "at":
                if f[1] in men:
                    at_man[f[1]] = f[2]
                elif f[1] in spanners:
                    at_sp[f[1]] = f[2]
                elif f[1] in nuts:
                    pass
        for f in state:
            if f[0] == "carrying":
                carrying[f[1]] = f[2]
        loose = set(f[1] for f in state if f[0] == "loose")
        useable = set(f[1] for f in state if f[0] == "useable")
        link = set((f[1], f[2]) for f in state if f[0] == "link")

        acts = []
        for m in men:
            cur = at_man.get(m)
            if cur is None:
                continue
            for (a, b) in link:
                if a == cur:
                    acts.append(("walk(%s,%s,%s)" % (a, b, m),
                                set([("at", m, b)]), set([("at", m, a)])))
            for s in spanners:
                if at_sp.get(s) == cur:
                    acts.append(("pickup_spanner(%s,%s,%s)" % (cur, s, m),
                                set([("carrying", m, s)]), set([("at", s, cur)])))
            held = carrying.get(m)
            if held is not None and held in useable:
                for n in nuts:
                    if ("at", n, cur) in state and n in loose:
                        acts.append(("tighten_nut(%s,%s,%s,%s)" % (cur, held, m, n),
                                    set([("tightened", n)]),
                                    set([("loose", n), ("useable", held)])))
        return acts

    def goal_ok(state):
        return goals <= state

    start = frozenset(init)
    if goal_ok(start):
        return []

    from collections import deque
    visited = set([start])
    queue = deque([(start, [])])
    limit = 400000
    expanded = 0
    while queue and expanded < limit:
        state, plan = queue.popleft()
        expanded += 1
        for act_str, add, dele in actions(state):
            new_state = frozenset((set(state) | add) - dele)
            if new_state in visited:
                continue
            new_plan = plan + [act_str]
            if goal_ok(new_state):
                return new_plan[:1000]
            visited.add(new_state)
            queue.append((new_state, new_plan))
    return []