import argparse
import json
from pathlib import Path

import yaml

from src.pathway import edges, node_key, signed
from src.schemas import PathwayGraph, SystemSchema


def rates(predicted, expected):
    hits = len(predicted & expected)
    precision = hits / len(predicted) if predicted else 0.0
    recall = hits / len(expected) if expected else 0.0
    total = precision + recall
    return {
        "tp": hits,
        "fp": len(predicted - expected),
        "fn": len(expected - predicted),
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / total if total else 0.0,
    }


def mechanism(edge):
    source, target = edge
    return source[:2], target[:2]


def mechanisms(graph_edges):
    return {mechanism(edge) for edge in graph_edges}


def directions(graph_edges):
    found = {}
    for edge in graph_edges:
        found.setdefault(mechanism(edge), set()).add((edge[0][2], edge[1][2]))
    return found


def direction_scores(predicted_edges, expected_edges):
    predicted = directions(predicted_edges)
    expected = directions(expected_edges)
    evaluated = predicted.keys() & expected.keys()
    correct = {item for item in evaluated if predicted[item] == expected[item]}
    wrong = [
        {
            "mechanism": item,
            "predicted": sorted(predicted[item]),
            "expected": sorted(expected[item]),
        }
        for item in sorted(evaluated - correct)
    ]
    return {
        "correct": len(correct),
        "evaluated": len(evaluated),
        "accuracy": len(correct) / len(evaluated) if evaluated else None,
    }, wrong


def index_graph(pathway):
    nodes_by_id = {event["id"]: node_key(event) for event in pathway["events"]}
    outgoing = {}
    for edge in pathway["edges"]:
        outgoing.setdefault(edge["source"], set()).add(edge["target"])
    return nodes_by_id, outgoing


def causal_paths(pathway):
    nodes_by_id, outgoing = index_graph(pathway)
    found = set()

    def walk(event_path):
        targets = outgoing.get(event_path[-1], set())
        if not targets:
            if len(event_path) > 1:
                found.add(tuple(nodes_by_id[event_id] for event_id in event_path))
            return
        for target in sorted(targets):
            if target in event_path:
                raise ValueError("ground-truth graph contains a cycle")
            walk(event_path + (target,))

    for event_id in sorted(pathway["input_event_ids"]):
        walk((event_id,))
    return found


def contains_path(path, input_event_ids, nodes_by_id, outgoing):
    current = {event_id for event_id in input_event_ids if nodes_by_id[event_id] == path[0]}
    for expected_node in path[1:]:
        current = {
            target
            for source in current
            for target in outgoing.get(source, set())
            if nodes_by_id[target] == expected_node
        }
        if not current:
            return False
    return bool(current)


def path_scores(prediction, truth):
    expected_paths = causal_paths(truth)
    if not expected_paths:
        raise ValueError("ground truth has no causal input-to-terminal paths")
    nodes_by_id, outgoing = index_graph(prediction)
    recovered = {
        path
        for path in expected_paths
        if contains_path(path, prediction["input_event_ids"], nodes_by_id, outgoing)
    }
    broken = sorted(expected_paths - recovered)
    return {
        "recovered": len(recovered),
        "total": len(expected_paths),
        "recall": len(recovered) / len(expected_paths),
    }, broken


def evaluate(prediction, truth):
    if prediction["scenario_id"] != truth["scenario_id"]:
        raise ValueError(
            f"prediction scenario '{prediction['scenario_id']}' does not match "
            f"ground truth '{truth['scenario_id']}'"
        )

    predicted_edges = edges(prediction)
    expected_edges = edges(truth)
    predicted_mechanisms = mechanisms(predicted_edges)
    expected_mechanisms = mechanisms(expected_edges)
    mechanism_scores = rates(predicted_mechanisms, expected_mechanisms)
    direction, wrong_directions = direction_scores(predicted_edges, expected_edges)
    paths, broken_paths = path_scores(prediction, truth)
    return {
        "scenario_id": truth["scenario_id"],
        "mechanisms": mechanism_scores,
        "directions": direction,
        "complete_paths": paths,
        "diagnostics": {
            "missed_mechanisms": sorted(expected_mechanisms - predicted_mechanisms),
            "spurious_mechanisms": sorted(predicted_mechanisms - expected_mechanisms),
            "wrong_directions": wrong_directions,
            "broken_paths": broken_paths,
        },
    }


def render_concept(node):
    return f"{node[0]}.{node[1]}"


def render_node(node):
    return f"{node[0]}.{signed(node[1], node[2])}"


def render_mechanism(item):
    return f"{render_concept(item[0])} → {render_concept(item[1])}"


def render_path(path):
    return " → ".join(render_node(node) for node in path)


def listing(title, items, render):
    print(f"\n{title} ({len(items)})")
    for item in items:
        print(f"    {render(item)}")


def report(result):
    mechanisms = result["mechanisms"]
    directions = result["directions"]
    paths = result["complete_paths"]
    direction_accuracy = (
        f"{directions['accuracy']:.3f}" if directions["accuracy"] is not None else "n/a"
    )
    print("\n=== PRIMARY ===\n")
    print(f"Mechanism F1       {mechanisms['f1']:.3f}"
          f"     P {mechanisms['precision']:.3f}  R {mechanisms['recall']:.3f}"
          f"   (TP {mechanisms['tp']}  FP {mechanisms['fp']}  FN {mechanisms['fn']})")
    print(f"Direction accuracy {direction_accuracy}"
          f"     ({directions['correct']}/{directions['evaluated']} matched mechanisms)")
    print(f"Complete path recall {paths['recall']:.3f}"
          f"   ({paths['recovered']}/{paths['total']} GT paths)")

    diagnostics = result["diagnostics"]
    print("\n=== DIAGNOSTICS ===")
    listing("Missed mechanisms", diagnostics["missed_mechanisms"], render_mechanism)
    listing("Spurious mechanisms", diagnostics["spurious_mechanisms"], render_mechanism)
    listing("Broken paths", diagnostics["broken_paths"], render_path)
    print(f"\nWrong directions ({len(diagnostics['wrong_directions'])})")
    for entry in diagnostics["wrong_directions"]:
        predicted = ", ".join(f"{source}→{target}" for source, target in entry["predicted"])
        expected = ", ".join(f"{source}→{target}" for source, target in entry["expected"])
        print(f"    {render_mechanism(entry['mechanism'])}"
              f"   predicted {predicted}; expected {expected}")


def load_graph(path, schema):
    graph = PathwayGraph.model_validate_json(path.read_text())
    schema.validate_graph(graph)
    return graph.model_dump(exclude_none=True)


def main():
    parser = argparse.ArgumentParser(description="Score a canonical pathway graph against ground truth")
    parser.add_argument("--pathway", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--schema", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    schema = SystemSchema.compose(
        yaml.safe_load(path.read_text()) for path in args.schema
    )
    result = evaluate(
        load_graph(args.pathway, schema),
        load_graph(args.truth, schema),
    )
    report(result)

    if args.output:
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"\nSaved to {args.output}")


if __name__ == "__main__":
    main()
