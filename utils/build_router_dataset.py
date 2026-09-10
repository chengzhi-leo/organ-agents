import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.schemas import FLIP, PathwayGraph, SystemSchema


def project_path(path):
    return path if path.is_absolute() else ROOT / path


def load_yaml(path):
    return yaml.safe_load(project_path(path).read_text())


def load_schema(catalog, shared):
    return SystemSchema.compose([load_yaml(catalog), load_yaml(shared)])


def ground_truth_paths(directory):
    paths = sorted(project_path(directory).glob("*.json"))
    if not paths:
        raise ValueError(f"no ground-truth graphs found in '{directory}'")
    return paths


def ordered_agents(agent_ids, schema):
    selected = set(agent_ids)
    return [agent_id for agent_id in schema.agents if agent_id in selected]


def event_payload(event):
    return {
        "event_id": event.id,
        "source_component": event.agent_id,
        "variable": event.variable,
        "level": event.level,
    }


def build_case(path, schema):
    graph = PathwayGraph.model_validate_json(path.read_text())
    schema.validate_graph(graph)
    if len(graph.input_event_ids) != 1:
        raise ValueError(f"ground truth '{path}' must have exactly one input event")
    if not graph.required_agents:
        raise ValueError(f"scenario '{graph.scenario_id}' has no required_agents")
    if len(graph.required_agents) != len(set(graph.required_agents)):
        raise ValueError(f"scenario '{graph.scenario_id}' has duplicate required_agents")
    unknown = set(graph.required_agents) - set(schema.agents)
    if unknown:
        raise ValueError(
            f"scenario '{graph.scenario_id}' requires unavailable agents: {sorted(unknown)}"
        )

    events = {event.id: event for event in graph.events}
    outgoing = {}
    for edge in graph.edges:
        outgoing.setdefault(edge.source, []).append(events[edge.target])
    initial = events[graph.input_event_ids[0]]
    transforms = {transform.source: transform for transform in schema.blood.transforms}
    translation_only = set()
    translated_with_agent_routes = set()
    samples = []

    for event in graph.events:
        transform = transforms.get(event.variable)
        expected = {
            target.agent_id
            for target in outgoing.get(event.id, [])
            if target.agent_id != "blood"
        }
        if transform is not None and not expected:
            translation_only.add(event.id)
            continue
        if transform is not None:
            translated_with_agent_routes.add(event.id)
        is_closure = (
            event.type == "response"
            and event.variable == initial.variable
            and event.level == FLIP[initial.level]
        )
        if is_closure:
            continue
        outside_scope = expected - set(graph.required_agents)
        if outside_scope:
            raise ValueError(
                f"event '{event.id}' routes outside required_agents: {sorted(outside_scope)}"
            )
        samples.append(
            {
                "sample_id": f"{graph.scenario_id}:{event.id}",
                "event": event_payload(event),
                "expected_agents": ordered_agents(expected, schema),
            }
        )

    return {
        "scenario_id": graph.scenario_id,
        "ground_truth": str(path.relative_to(ROOT)),
        "candidate_agents": ordered_agents(graph.required_agents, schema),
        "samples": samples,
        "excluded": {
            "blood_translation_only_events": len(translation_only),
            "homeostatic_closures": sum(
                event.type == "response"
                and event.variable == initial.variable
                and event.level == FLIP[initial.level]
                for event in graph.events
            ),
        },
        "included": {
            "blood_translation_events_with_agent_routes": len(
                translated_with_agent_routes
            ),
        },
    }


def summarize(cases):
    samples = [sample for case in cases for sample in case["samples"]]
    return {
        "case_count": len(cases),
        "sample_count": len(samples),
        "positive_route_pairs": sum(
            len(sample["expected_agents"]) for sample in samples
        ),
        "empty_expected_sets": sum(
            not sample["expected_agents"] for sample in samples
        ),
        "blood_translation_only_events_excluded": sum(
            case["excluded"]["blood_translation_only_events"] for case in cases
        ),
        "homeostatic_closures_excluded": sum(
            case["excluded"]["homeostatic_closures"] for case in cases
        ),
        "blood_translation_events_with_agent_routes_included": sum(
            case["included"]["blood_translation_events_with_agent_routes"]
            for case in cases
        ),
    }


def build(catalog, shared, ground_truth_dir):
    schema = load_schema(catalog, shared)
    cases = [
        build_case(path, schema)
        for path in ground_truth_paths(ground_truth_dir)
    ]
    scenario_ids = [case["scenario_id"] for case in cases]
    if len(scenario_ids) != len(set(scenario_ids)):
        raise ValueError("router dataset scenario IDs must be unique")
    return {
        "scope": "oracle_required_agents",
        "catalog": str(catalog),
        "shared": str(shared),
        "ground_truth_directory": str(ground_truth_dir),
        "cases": cases,
        "summary": summarize(cases),
    }


def main():
    parser = argparse.ArgumentParser(description="Build an Oracle-scope Router dataset")
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--shared", type=Path, required=True)
    parser.add_argument("--ground-truth-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = build(args.catalog, args.shared, args.ground_truth_dir)
    output = project_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(data["summary"], indent=2))
    print(f"Saved to {output}")


if __name__ == "__main__":
    main()
