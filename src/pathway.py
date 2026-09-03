from collections import deque

from src.schemas import PathwayGraph

ARROWS = {"decreased": "↓", "increased": "↑"}


def signed(variable, level):
    return f"{variable} {ARROWS[level]}"


def node_key(event):
    return event["agent_id"], event["variable"], event["level"]


def nodes(pathway):
    return {node_key(event) for event in pathway["events"]}


def edges(pathway):
    events_by_id = {event["id"]: event for event in pathway["events"]}
    return {
        (node_key(events_by_id[edge["source"]]), node_key(events_by_id[edge["target"]]))
        for edge in pathway["edges"]
    }


def build(scenario_id, events, vocabulary, validate_vocabulary):
    canonical_events, canonical_edges = _canonicalize(events)
    graph = PathwayGraph(
        scenario_id=scenario_id,
        input_event_ids=[event.id for event in events if event.type == "input"],
        events=canonical_events,
        edges=canonical_edges,
    )
    if validate_vocabulary:
        vocabulary.validate_graph(graph)
    return graph.model_dump(exclude_none=True)


def _canonicalize(events):
    canonical_events = []
    canonical_ids = {}
    response_ids = {}

    for event in events:
        if event.type == "input":
            canonical_events.append(event.graph_dump())
            canonical_ids[event.id] = event.id
            continue
        if event.key not in response_ids:
            response_ids[event.key] = event.id
            canonical_events.append(event.graph_dump())
        canonical_ids[event.id] = response_ids[event.key]

    canonical_edges = []
    edge_keys = set()
    for event in events:
        if event.caused_by is None:
            continue
        if event.caused_by not in canonical_ids:
            raise ValueError(
                f"event '{event.id}' cites unknown cause '{event.caused_by}'"
            )
        edge = canonical_ids[event.caused_by], canonical_ids[event.id]
        if edge[0] == edge[1] or edge in edge_keys:
            continue
        edge_keys.add(edge)
        canonical_edges.append({"source": edge[0], "target": edge[1]})

    return canonical_events, canonical_edges


def event_adjacency(pathway):
    outgoing = {}
    for edge in pathway["edges"]:
        outgoing.setdefault(edge["source"], []).append(edge["target"])
    return outgoing


def longest_chain(pathway):
    outgoing = event_adjacency(pathway)
    best = []

    def walk(path):
        nonlocal best
        if len(path) > len(best):
            best = list(path)
        for node in outgoing.get(path[-1], []):
            if node not in path:
                walk(path + [node])

    for start in outgoing:
        walk([start])
    return best


def depths(pathway):
    outgoing = event_adjacency(pathway)
    found = {event_id: 0 for event_id in pathway["input_event_ids"]}
    queue = deque(pathway["input_event_ids"])
    while queue:
        source = queue.popleft()
        for target in outgoing.get(source, []):
            if target not in found:
                found[target] = found[source] + 1
                queue.append(target)
    return found


def display_node_key(event):
    return event["id"], event["agent_id"], event["variable"], event["level"]


def display_edges(pathway):
    events_by_id = {event["id"]: event for event in pathway["events"]}
    layered = depths(pathway)
    unreached = max(layered.values(), default=-1) + 1
    rendered = []
    for edge in pathway["edges"]:
        source = events_by_id[edge["source"]]
        target = events_by_id[edge["target"]]
        source_key = display_node_key(source)
        target_key = display_node_key(target)
        rendered.append({
            "source": source_key,
            "target": target_key,
            "round": layered.get(source["id"], unreached),
        })
    return rendered
