"""Hand-authored deterministic Spanner installation fixture, not an RSI result.

Derive the forward route from the current input, collect available spanners,
then consume one spanner per loose goal nut. No problem-specific plan is stored.
"""


def get_plan(objects, init, goal):
    kinds = dict(objects)
    people = sorted(name for name, kind in objects if kind == "man")
    if len(people) != 1:
        raise ValueError("Fixture expects one man")
    person = people[0]
    positions = {atom[1]: atom[2] for atom in init if atom[0] == "at"}
    links = {}
    for atom in init:
        if atom[0] == "link":
            links.setdefault(atom[1], []).append(atom[2])
    available = {atom[1] for atom in init if atom[0] == "useable"}
    loose = {atom[1] for atom in init if atom[0] == "loose"}
    goals = {atom[1] for atom in goal if atom[0] == "tightened"}
    carrying = sorted(atom[2] for atom in init if atom[0] == "carrying" and atom[1] == person and atom[2] in available)
    position, plan, visited = positions[person], [], set()
    while True:
        if position in visited:
            raise ValueError("Fixture expects an acyclic forward route")
        visited.add(position)
        for spanner in sorted(name for name, kind in objects if kind == "spanner" and positions.get(name) == position and name in available):
            plan.append(f"(pickup_spanner {position} {spanner} {person})")
            carrying.append(spanner)
        for nut in sorted(name for name in goals & loose if positions.get(name) == position):
            if not carrying:
                raise ValueError("Insufficient spanners on the forward route")
            spanner = carrying.pop(0)
            plan.append(f"(tighten_nut {position} {spanner} {person} {nut})")
            loose.remove(nut)
        destinations = sorted(links.get(position, []))
        if not destinations:
            break
        if len(destinations) != 1:
            raise ValueError("Fixture expects an unbranched route")
        destination = destinations[0]
        plan.append(f"(walk {position} {destination} {person})")
        position = destination
    if goals & loose:
        raise ValueError("Unreached goal nuts")
    return plan
