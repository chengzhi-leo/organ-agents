ARROWS = {"decreased": "↓", "increased": "↑"}


def signed(variable, level):
    return f"{variable} {ARROWS[level]}"


def emitters(records, perturbation=None):
    sources = {}
    if perturbation:
        sources[(perturbation["variable"], perturbation["level"])] = perturbation["source_agent"]
    for entry in records:
        for event in entry["incoming"]:
            sources.setdefault((event["variable"], event["level"]), event["source_agent"])
        for effect in entry["effects"]:
            sources.setdefault((effect["variable"], effect["level"]), entry["agent"])
    return sources


def variable_edges(records, perturbation=None):
    sources = emitters(records, perturbation)
    edges = {}
    for entry in records:
        for effect in entry["effects"]:
            for cause in effect["caused_by"]:
                key = (cause["variable"], cause["level"])
                edge = {
                    "from": cause["variable"],
                    "from_level": cause["level"],
                    "from_agent": sources.get(key, "introduced"),
                    "to": effect["variable"],
                    "to_level": effect["level"],
                    "agent": entry["agent"],
                    "round": entry["round"],
                }
                identity = tuple(
                    edge[field] for field in ("from", "from_level", "to", "to_level", "agent")
                )
                edges.setdefault(identity, edge)
    return list(edges.values())


def agent_edges(edges):
    projected = {}
    for edge in edges:
        entry = projected.setdefault(
            (edge["from_agent"], edge["agent"]),
            {"from": edge["from_agent"], "to": edge["agent"], "via": [], "rounds": []},
        )
        carried = signed(edge["from"], edge["from_level"])
        if carried not in entry["via"]:
            entry["via"].append(carried)
        if edge["round"] not in entry["rounds"]:
            entry["rounds"].append(edge["round"])
    return list(projected.values())


def longest_chain(edges):
    adjacency = {}
    for edge in edges:
        adjacency.setdefault((edge["from"], edge["from_level"]), []).append(
            (edge["to"], edge["to_level"])
        )

    best = []

    def walk(path):
        nonlocal best
        if len(path) > len(best):
            best = list(path)
        for node in adjacency.get(path[-1], []):
            if node not in path:
                walk(path + [node])

    for start in adjacency:
        walk([start])
    return best


def build(records, perturbation):
    edges = variable_edges(records, perturbation)
    return {
        "variable_edges": edges,
        "agent_edges": agent_edges(edges),
        "longest_chain": longest_chain(edges),
    }
