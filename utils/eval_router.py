import argparse
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.body import Body
from src.llm import LLM
from src.meta_agent import evaluate_selection, selection_metrics
from src.router import LLMRouter, ROUTER_SYSTEM_PROMPT
from src.schemas import Event, SystemSchema


def project_path(path):
    path = Path(path)
    return path if path.is_absolute() else ROOT / path


def load_yaml(path):
    return yaml.safe_load(project_path(path).read_text())


def load_json(path):
    return json.loads(project_path(path).read_text())


def validate_config(config):
    if config["router"]["mode"] != "llm":
        raise ValueError("Router evaluation requires router.mode 'llm'")
    if config["evaluation"]["mode"] != "atomic":
        raise ValueError("Router evaluation requires evaluation.mode 'atomic'")
    if config["evaluation"]["workers"] <= 0:
        raise ValueError("evaluation.workers must be positive")


def validate_dataset(dataset, schema):
    if dataset["scope"] != "oracle_required_agents":
        raise ValueError("Router evaluation requires an Oracle-scope dataset")
    sample_ids = []
    for case in dataset["cases"]:
        candidates = case["candidate_agents"]
        if not candidates:
            raise ValueError(f"scenario '{case['scenario_id']}' has no candidate agents")
        if len(candidates) != len(set(candidates)):
            raise ValueError(
                f"scenario '{case['scenario_id']}' has duplicate candidate agents"
            )
        unknown = set(candidates) - set(schema.agents)
        if unknown:
            raise ValueError(
                f"scenario '{case['scenario_id']}' has unknown candidate agents: "
                f"{sorted(unknown)}"
            )
        for sample in case["samples"]:
            sample_ids.append(sample["sample_id"])
            expected = sample["expected_agents"]
            if len(expected) != len(set(expected)):
                raise ValueError(f"sample '{sample['sample_id']}' has duplicate labels")
            outside_scope = set(expected) - set(candidates)
            if outside_scope:
                raise ValueError(
                    f"sample '{sample['sample_id']}' routes outside Oracle scope: "
                    f"{sorted(outside_scope)}"
                )
    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError("Router dataset sample IDs must be unique")
    if len(sample_ids) != dataset["summary"]["sample_count"]:
        raise ValueError("Router dataset sample count does not match its summary")


def build_tasks(dataset, schema, llm, knowledge_dir):
    tasks = []
    for case in dataset["cases"]:
        body = Body(schema, llm, knowledge_dir, case["candidate_agents"])
        event_router = LLMRouter(body, llm)
        for sample in case["samples"]:
            tasks.append(
                (case["scenario_id"], case["candidate_agents"], sample, event_router)
            )
    return tasks


def evaluate_task(task):
    scenario_id, candidate_agents, sample, event_router = task
    payload = sample["event"]
    event = Event(
        id=payload["event_id"],
        agent_id=payload["source_component"],
        variable=payload["variable"],
        level=payload["level"],
        type="response",
        caused_by=None,
        round=0,
    )
    routing = event_router.route([event])
    if len(routing.decisions) != 1:
        raise RuntimeError(f"sample '{sample['sample_id']}' returned multiple decisions")
    selected = [agent.id for agent in routing.decisions[0].agents]
    expected = sample["expected_agents"]
    return {
        "sample_id": sample["sample_id"],
        "scenario_id": scenario_id,
        "event": payload,
        "candidate_agents": candidate_agents,
        "expected_agents": expected,
        "selected_agents": selected,
        "metrics": evaluate_selection(selected, expected),
        "trace": routing.trace.dump(),
    }


def macro_metrics(results):
    nonempty = [result["metrics"] for result in results if result["expected_agents"]]
    return {
        metric: sum(item[metric] for item in nonempty) / len(nonempty)
        for metric in ("precision", "recall", "f1")
    }


def aggregate(results):
    metrics = [result["metrics"] for result in results]
    micro = selection_metrics(
        sum(item["tp"] for item in metrics),
        sum(item["fp"] for item in metrics),
        sum(item["fn"] for item in metrics),
    )
    empty = [result for result in results if not result["expected_agents"]]
    return {
        "micro": micro,
        "macro_nonempty_expected": macro_metrics(results),
        "exact_matches": sum(item["exact_match"] for item in metrics),
        "sample_count": len(results),
        "empty_expected_sets": len(empty),
        "correct_empty_predictions": sum(not item["selected_agents"] for item in empty),
        "expected_route_pairs": sum(len(item["expected_agents"]) for item in results),
        "predicted_route_pairs": sum(len(item["selected_agents"]) for item in results),
    }


def per_scenario(results):
    grouped = {}
    for result in results:
        grouped.setdefault(result["scenario_id"], []).append(result)
    return {
        scenario_id: aggregate(items)
        for scenario_id, items in grouped.items()
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


def run(config):
    validate_config(config)
    dataset = load_json(config["dataset"])
    schema = SystemSchema.compose(
        [load_yaml(Path(dataset["catalog"])), load_yaml(Path(dataset["shared"]))]
    )
    validate_dataset(dataset, schema)
    llm_config = load_yaml(config["llm_config"])
    llm = LLM(llm_config)
    tasks = build_tasks(
        dataset,
        schema,
        llm,
        project_path(config["knowledge"]),
    )
    with ThreadPoolExecutor(max_workers=config["evaluation"]["workers"]) as pool:
        results = list(pool.map(evaluate_task, tasks))
    if llm.call_count != len(results):
        raise RuntimeError("LLM call count does not match Router result count")
    return {
        "model": llm.model,
        "prompt_sha256": hashlib.sha256(ROUTER_SYSTEM_PROMPT.encode()).hexdigest(),
        "dataset": str(config["dataset"]),
        "workers": config["evaluation"]["workers"],
        "results": results,
        "summary": aggregate(results),
        "per_scenario": per_scenario(results),
        "usage": usage(results),
    }


def print_summary(data):
    summary = data["summary"]
    micro = summary["micro"]
    macro = summary["macro_nonempty_expected"]
    print(
        f"micro P {micro['precision']:.3f} R {micro['recall']:.3f} "
        f"F1 {micro['f1']:.3f} TP {micro['tp']} FP {micro['fp']} FN {micro['fn']}"
    )
    print(
        f"macro-nonempty P {macro['precision']:.3f} R {macro['recall']:.3f} "
        f"F1 {macro['f1']:.3f}"
    )
    print(
        f"exact {summary['exact_matches']}/{summary['sample_count']} "
        f"empty {summary['correct_empty_predictions']}/"
        f"{summary['empty_expected_sets']}"
    )
    print(
        f"routes expected {summary['expected_route_pairs']} "
        f"predicted {summary['predicted_route_pairs']}"
    )
    print(
        f"calls {data['usage']['llm_calls']} "
        f"tokens {data['usage']['total_tokens']:,}"
    )


def main():
    parser = argparse.ArgumentParser(description="Evaluate the LLM Router")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = load_yaml(args.config)
    data = run(config)
    output = project_path(Path(config["output"])) / datetime.now().strftime(
        "%Y%m%d/%H%M%S"
    )
    output.mkdir(parents=True)
    (output / "results.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output / "config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )
    print_summary(data)
    print(f"Saved to {output}")


if __name__ == "__main__":
    main()
