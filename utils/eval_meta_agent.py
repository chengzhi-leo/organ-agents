import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.llm import LLM
from src.meta_agent import MetaAgent, evaluate_selection, selection_metrics
from src.schemas import PathwayGraph, ScenarioInput, SystemSchema


def load_yaml(path):
    return yaml.safe_load((ROOT / path).read_text())


def load_cases(config, catalog_schema):
    cases = []
    for entry in config["cases"]:
        ground_truth_path = ROOT / entry["ground_truth"]
        graph = PathwayGraph.model_validate_json(ground_truth_path.read_text())
        catalog_schema.validate_graph(graph)
        input_events = [
            event for event in graph.events if event.id in graph.input_event_ids
        ]
        if len(input_events) != 1:
            raise ValueError(
                f"ground truth '{ground_truth_path}' must have exactly one input event"
            )
        input_event = input_events[0]
        scenario = ScenarioInput(
            scenario_id=graph.scenario_id,
            agent_id=input_event.agent_id,
            variable=input_event.variable,
            level=input_event.level,
        )
        required = graph.required_agents
        if not required:
            raise ValueError(f"scenario '{scenario.scenario_id}' has no required_agents")
        if len(required) != len(set(required)):
            raise ValueError(
                f"scenario '{scenario.scenario_id}' has duplicate required_agents"
            )
        unknown = set(required) - set(catalog_schema.agents)
        if unknown:
            raise ValueError(
                f"scenario '{scenario.scenario_id}' requires unavailable agents: "
                f"{sorted(unknown)}"
            )
        expected = [
            agent_id for agent_id in catalog_schema.agents if agent_id in required
        ]
        cases.append((scenario, expected, entry["ground_truth"]))
    scenario_ids = [scenario.scenario_id for scenario, _, _ in cases]
    if len(scenario_ids) != len(set(scenario_ids)):
        raise ValueError("Meta Agent scenario IDs must be unique")
    if not cases:
        raise ValueError("Meta Agent experiment requires at least one case")
    return cases


def run(config):
    llm_config = load_yaml(config["llm_config"])
    shared = load_yaml(config["shared"])
    catalog_schema = SystemSchema.compose([load_yaml(config["catalog"]), shared])
    cases = load_cases(config, catalog_schema)
    llm = LLM(llm_config)
    agent = MetaAgent(catalog_schema.agents, llm)
    results = []
    for scenario, expected, ground_truth in cases:
        selection = agent.select(scenario)
        results.append(
            {
                "scenario_id": scenario.scenario_id,
                "input": scenario.model_dump(),
                "ground_truth": ground_truth,
                "expected_agents": expected,
                "selected_agents": selection.agent_ids,
                "metrics": evaluate_selection(selection.agent_ids, expected),
                "trace": selection.trace.dump(),
            }
        )
        print_result(results[-1])
    return {
        "model": llm.model,
        "llm_config": {
            key: llm_config[key]
            for key in ("model", "generation", "token_counting")
        },
        "catalog": config["catalog"],
        "results": results,
        "summary": summarize(results),
        "usage": usage(results),
    }


def usage(results):
    traces = [result["trace"] for result in results]
    return {
        "llm_calls": len(traces),
        "prompt_tokens": sum(trace["prompt_tokens"] for trace in traces),
        "cached_tokens": sum(trace["cached_tokens"] for trace in traces),
        "output_tokens": sum(trace["output_tokens"] for trace in traces),
        "total_tokens": sum(trace["total_tokens"] for trace in traces),
    }


def summarize(results):
    per_case = [result["metrics"] for result in results]
    micro = selection_metrics(
        sum(metrics["tp"] for metrics in per_case),
        sum(metrics["fp"] for metrics in per_case),
        sum(metrics["fn"] for metrics in per_case),
    )
    return {
        "micro": micro,
        "macro": {
            metric: sum(metrics[metric] for metrics in per_case) / len(per_case)
            for metric in ("precision", "recall", "f1")
        },
        "exact_matches": sum(metrics["exact_match"] for metrics in per_case),
        "case_count": len(per_case),
    }


def print_result(result):
    metrics = result["metrics"]
    print(f"\n{result['scenario_id']}")
    print(f"  expected: {', '.join(result['expected_agents'])}")
    print(f"  selected: {', '.join(result['selected_agents'])}")
    print(
        f"  P {metrics['precision']:.3f}  R {metrics['recall']:.3f}  "
        f"F1 {metrics['f1']:.3f}  exact {metrics['exact_match']}"
    )


def print_summary(summary):
    micro = summary["micro"]
    macro = summary["macro"]
    print("\nOverall")
    print(
        f"  micro P {micro['precision']:.3f}  R {micro['recall']:.3f}  "
        f"F1 {micro['f1']:.3f}  "
        f"TP {micro['tp']}  FP {micro['fp']}  FN {micro['fn']}"
    )
    print(
        f"  macro P {macro['precision']:.3f}  R {macro['recall']:.3f}  "
        f"F1 {macro['f1']:.3f}"
    )
    print(f"  exact {summary['exact_matches']}/{summary['case_count']}")


def report(data):
    rows = []
    for result in data["results"]:
        metrics = result["metrics"]
        rows.append(
            f"| {result['scenario_id']} | {', '.join(result['expected_agents'])} | "
            f"{', '.join(result['selected_agents'])} | "
            f"{metrics['tp']} / {metrics['fp']} / {metrics['fn']} | "
            f"{metrics['precision']:.3f} | {metrics['recall']:.3f} | "
            f"{metrics['f1']:.3f} | {metrics['exact_match']} |"
        )
    summary = data["summary"]
    micro = summary["micro"]
    macro = summary["macro"]
    usage_data = data["usage"]
    return "\n".join(
        [
            "# Meta Agent Selection",
            "",
            f"Model: `{data['model']}`",
            "",
            f"Catalog: `{data['catalog']}`",
            "",
            "| Scenario | Expected | Selected | TP / FP / FN | Precision | Recall | F1 | Exact |",
            "|---|---|---|---:|---:|---:|---:|---:|",
            *rows,
            "",
            "| Aggregation | TP / FP / FN | Precision | Recall | F1 |",
            "|---|---:|---:|---:|---:|",
            f"| Micro | {micro['tp']} / {micro['fp']} / {micro['fn']} | "
            f"{micro['precision']:.3f} | {micro['recall']:.3f} | {micro['f1']:.3f} |",
            f"| Macro | — | {macro['precision']:.3f} | {macro['recall']:.3f} | "
            f"{macro['f1']:.3f} |",
            "",
            f"Exact matches: {summary['exact_matches']}/{summary['case_count']}",
            "",
            f"LLM calls: {usage_data['llm_calls']}",
            "",
            f"Total tokens: {usage_data['total_tokens']:,}",
            "",
        ]
    )


def main():
    parser = argparse.ArgumentParser(description="Evaluate Meta Agent selection")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = load_yaml(args.config)
    data = run(config)
    print_summary(data["summary"])
    output = ROOT / config["output"] / datetime.now().strftime("%Y%m%d/%H%M%S")
    output.mkdir(parents=True)
    (output / "results.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output / "report.md").write_text(report(data), encoding="utf-8")
    (output / "config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )
    print(f"\nSaved to {output}")


if __name__ == "__main__":
    main()
