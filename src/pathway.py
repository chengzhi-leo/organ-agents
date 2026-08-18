ARROWS = {None: "", "decreased": "↓", "increased": "↑"}


def signed(variable, level):
    return f"{variable} {ARROWS[level]}".rstrip()


def variable_edges(records, perturbation=None):
    edges = {}
    observed = {}
    if perturbation:
        observed[perturbation["variable"]] = (perturbation["level"], perturbation["source_agent"])

    for entry in records:
        for event in entry["incoming"]:
            observed[event["variable"]] = (event["level"], event["source_agent"])
        for effect in entry["effects"]:
            observed[effect["variable"]] = (effect["level"], entry["agent"])

        for effect in entry["effects"]:
            for cause in effect["caused_by"]:
                level, source = observed.get(cause, (None, "introduced"))
                edge = {
                    "from": cause,
                    "from_level": level,
                    "from_agent": source,
                    "to": effect["variable"],
                    "to_level": effect["level"],
                    "agent": entry["agent"],
                    "round": entry["round"],
                }
                key = tuple(
                    edge[field] for field in ("from", "from_level", "to", "to_level", "agent")
                )
                edges.setdefault(key, edge)
    return list(edges.values())


def agent_edges(records):
    edges = {}
    for entry in records:
        for event in entry["incoming"]:
            edge = edges.setdefault(
                (event["source_agent"], entry["agent"]),
                {"from": event["source_agent"], "to": entry["agent"], "via": [], "rounds": []},
            )
            carried = signed(event["variable"], event["level"])
            if carried not in edge["via"]:
                edge["via"].append(carried)
            if entry["round"] not in edge["rounds"]:
                edge["rounds"].append(entry["round"])
    return list(edges.values())


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
        "agent_edges": agent_edges(records),
        "longest_chain": longest_chain(edges),
    }
