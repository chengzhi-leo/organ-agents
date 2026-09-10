import argparse
import json
from datetime import datetime
from pathlib import Path

import yaml

from src.forward import run as run_forward
from src.llm import LLM, summarize_usage
from src.optimize import GraphOptimizer, graph_complexity, operation_dump
from src.schemas import Scenario, SystemSchema
from utils.report import build as build_report

ROOT = Path(__file__).parent


def load_yaml(path):
    return yaml.safe_load((ROOT / path).read_text())


def load_scenario(path, schema):
    scenario = Scenario.model_validate_json(path.read_text())
    schema.validate_perturbation(
        scenario.input.agent_id,
        scenario.input.variable,
        f"scenario '{scenario.scenario_id}' input",
    )
    for index, output in enumerate(scenario.output):
        schema.validate_owned_variable(
            output.agent_id,
            output.variable,
            f"scenario '{scenario.scenario_id}' output {index}",
        )
    return scenario


def validate_config(config):
    optimization = config["optimization"]
    if config["generation"]["temperature"] != 0:
        raise ValueError("optimization requires generation.temperature to be 0")
    for name in ("max_mutations", "patience", "rollouts_per_candidate"):
        if optimization[name] <= 0:
            raise ValueError(f"optimization.{name} must be positive")
    if optimization["rollouts_per_candidate"] != 1:
        raise ValueError("the current optimizer requires rollouts_per_candidate to be 1")
    if not isinstance(config["debug"]["verbose"], bool):
        raise ValueError("debug.verbose must be a boolean")


def run_scenario(config, schema, scenario, run_dir):
    llm = LLM(config)
    optimizer = GraphOptimizer(schema, llm, config["optimization"])
    knowledge_dir = ROOT / config["body"]["knowledge"]
    forward_config = config["forward"]
    verbose = config["debug"]["verbose"]

    initial_graph, initial_meta = optimizer.initialize(scenario)
    initial_result = run_forward(
        initial_graph,
        scenario,
        schema,
        llm,
        knowledge_dir,
        forward_config,
    )
    initial_critique = optimizer.critique_initial(
        scenario,
        initial_graph,
        initial_result,
    )

    meta_calls = [initial_meta]
    critic_calls = [initial_critique]
    agent_calls = list(initial_result.calls)
    best_graph = initial_graph
    best_result = initial_result
    best_matches_output = initial_critique.value.prediction_matches_output
    recommendation = initial_critique.value.next_recommendation
    best_iteration = 0
    patience = 0
    attempts = []

    initial_attempt = {
        "iteration": 0,
        "kind": "initial",
        "valid": True,
        "accepted": True,
        "operations": [],
        "complexity": graph_complexity(initial_graph),
        "termination": initial_result.termination,
        "prediction_matches_output": best_matches_output,
        "decision_reason": "initial graph is the unconditional best",
    }
    attempts.append(initial_attempt)
    save_attempt(
        run_dir / "iterations" / "000_initial",
        initial_attempt,
        initial_graph,
        initial_result,
        initial_meta,
        initial_critique,
    )
    if verbose:
        print_iteration(scenario.scenario_id, initial_attempt, initial_graph)

    stop_reason = "max_mutations"
    for iteration in range(1, config["optimization"]["max_mutations"] + 1):
        operations, mutation_meta = optimizer.propose_mutation(
            best_graph,
            recommendation,
        )
        meta_calls.append(mutation_meta)
        operation_data = operation_dump(operations)
        attempt_dir = run_dir / "iterations" / f"{iteration:03d}_mutation"

        try:
            candidate_graph = optimizer.apply(best_graph, operations)
        except ValueError as error:
            patience += 1
            attempt = {
                "iteration": iteration,
                "kind": "mutation",
                "valid": False,
                "accepted": False,
                "operations": operation_data,
                "error": str(error),
            }
            attempts.append(attempt)
            save_attempt(attempt_dir, attempt, meta=mutation_meta)
            if verbose:
                print_iteration(scenario.scenario_id, attempt)
            if patience >= config["optimization"]["patience"]:
                stop_reason = "patience"
                break
            continue

        candidate_result = run_forward(
            candidate_graph,
            scenario,
            schema,
            llm,
            knowledge_dir,
            forward_config,
        )
        agent_calls.extend(candidate_result.calls)
        candidate_critique = optimizer.compare(
            scenario,
            best_graph,
            best_result,
            candidate_graph,
            candidate_result,
        )
        critic_calls.append(candidate_critique)
        accepted = candidate_critique.value.accept_candidate
        attempt = {
            "iteration": iteration,
            "kind": "mutation",
            "valid": True,
            "accepted": accepted,
            "operations": operation_data,
            "complexity": graph_complexity(candidate_graph),
            "termination": candidate_result.termination,
            "prediction_matches_output": (
                candidate_critique.value.prediction_matches_output
            ),
            "decision_reason": candidate_critique.value.decision_reason,
        }
        attempts.append(attempt)
        save_attempt(
            attempt_dir,
            attempt,
            candidate_graph,
            candidate_result,
            mutation_meta,
            candidate_critique,
        )

        if accepted:
            best_graph = candidate_graph
            best_result = candidate_result
            best_matches_output = candidate_critique.value.prediction_matches_output
            best_iteration = iteration
            patience = 0
        else:
            patience += 1
        recommendation = candidate_critique.value.next_recommendation
        if verbose:
            print_iteration(scenario.scenario_id, attempt, candidate_graph)
        if patience >= config["optimization"]["patience"]:
            stop_reason = "patience"
            break

    all_calls = meta_calls + critic_calls + agent_calls
    if llm.call_count != len(all_calls):
        raise RuntimeError("recorded LLM calls do not match the global call counter")
    usage = {
        **summarize_usage(all_calls),
        "initial_meta": summarize_usage(meta_calls[:1]),
        "mutation_meta": summarize_usage(meta_calls[1:]),
        "critic": summarize_usage(critic_calls),
        "agents": summarize_usage(agent_calls),
    }
    optimization = {
        "scenario_id": scenario.scenario_id,
        "status": "best_found",
        "stop_reason": stop_reason,
        "best_iteration": best_iteration,
        "mutations_attempted": len(attempts) - 1,
        "consecutive_non_improvements": patience,
        "input": scenario.input.model_dump(),
        "requested_output": [output.model_dump() for output in scenario.output],
        "best_prediction": best_result.dump(),
        "best_prediction_matches_output": best_matches_output,
        "best_complexity": best_graph.complexity,
        "best_graph_size": graph_complexity(best_graph),
        "attempts": attempts,
        "usage": usage,
    }
    save_best(run_dir, config, best_graph, best_result, optimization)
    report = build_report(run_dir)
    print(
        f"{scenario.scenario_id}: best iteration {best_iteration}, "
        f"complexity {best_graph.complexity}, stopped on {stop_reason}"
    )
    print(f"Report: {report}")


def save_attempt(
    directory,
    attempt,
    graph=None,
    result=None,
    meta=None,
    critique=None,
):
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / "attempt.json", attempt)
    if graph is not None:
        write_json(directory / "execution_graph.json", graph.model_dump())
    if result is not None:
        write_json(directory / "pathway.json", result.pathway)
        write_json(directory / "forward.json", result.dump())
        write_json(directory / "trace.json", result.trace)
    if meta is not None:
        write_json(directory / "meta.json", meta.dump())
    if critique is not None:
        write_json(directory / "critique.json", {
            "value": critique.value.model_dump(),
            "trace": critique.dump(),
        })


def save_best(directory, config, graph, result, optimization):
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / "best_execution_graph.json", graph.model_dump())
    write_json(directory / "best_pathway.json", result.pathway)
    write_json(directory / "best_trace.json", result.trace)
    write_json(directory / "optimization.json", optimization)
    (directory / "run_config.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False),
        encoding="utf-8",
    )


def write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def print_iteration(scenario_id, attempt, graph=None):
    status = "accepted" if attempt["accepted"] else "rejected"
    complexity = f", complexity={graph.complexity}" if graph is not None else ""
    detail = attempt.get("decision_reason", attempt.get("error", ""))
    print(
        f"[{scenario_id}] iteration={attempt['iteration']} {status}{complexity}: {detail}"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Iterative physiological agent graph optimization"
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--batch-id", type=Path)
    args = parser.parse_args()

    config = load_yaml(args.config)
    validate_config(config)
    body_config = config["body"]
    schema = SystemSchema.compose([
        load_yaml(body_config["definition"]),
        load_yaml(body_config["shared"]),
    ])
    scenario = load_scenario(args.scenario, schema)

    batch_id = args.batch_id or Path(datetime.now().strftime("%Y%m%d/%H%M%S"))
    if batch_id.is_absolute() or ".." in batch_id.parts:
        raise ValueError("batch ID must be a relative path without '..'")
    run_dir = ROOT / config["output"]["directory"] / batch_id / scenario.scenario_id
    run_scenario(config, schema, scenario, run_dir)
    print(f"Run saved to {run_dir}")


if __name__ == "__main__":
    main()
