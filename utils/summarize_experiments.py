import argparse
import json
from collections import Counter
from pathlib import Path

import yaml


def rate(numerator, denominator):
    return numerator / denominator if denominator else None


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def config_values(configs, keys):
    values = []
    for config in configs:
        value = config
        for key in keys:
            value = value[key]
        values.append(value)
    return sorted({str(value) for value in values})


def summarize_arm(arm_dir):
    cases = []
    for case_dir in sorted(path for path in arm_dir.iterdir() if path.is_dir()):
        run_path = case_dir / "run.json"
        evaluation_path = case_dir / "evaluation.json"
        if not run_path.exists() or not evaluation_path.exists():
            raise ValueError(f"incomplete case directory: {case_dir}")
        run = load_json(run_path)
        evaluation = load_json(evaluation_path)
        config = load_yaml(case_dir / "run_config.yaml")
        scenario_id = run["scenario_id"]
        if case_dir.name != scenario_id or evaluation["scenario_id"] != scenario_id:
            raise ValueError(f"scenario ID mismatch in {case_dir}")
        cases.append(
            {
                "scenario_id": scenario_id,
                "run": run,
                "evaluation": evaluation,
                "config": config,
            }
        )
    if not cases:
        raise ValueError(f"no completed cases in {arm_dir}")

    mechanisms = {
        key: sum(case["evaluation"]["mechanisms"][key] for case in cases)
        for key in ("tp", "fp", "fn")
    }
    precision = rate(mechanisms["tp"], mechanisms["tp"] + mechanisms["fp"])
    recall = rate(mechanisms["tp"], mechanisms["tp"] + mechanisms["fn"])
    mechanisms.update(
        {
            "precision": precision,
            "recall": recall,
            "f1": rate(2 * precision * recall, precision + recall)
            if precision is not None and recall is not None
            else None,
        }
    )
    directions = {
        key: sum(case["evaluation"]["directions"][key] for case in cases)
        for key in ("correct", "evaluated")
    }
    directions["accuracy"] = rate(directions["correct"], directions["evaluated"])
    complete_paths = {
        key: sum(case["evaluation"]["complete_paths"][key] for case in cases)
        for key in ("recovered", "total")
    }
    complete_paths["recall"] = rate(
        complete_paths["recovered"], complete_paths["total"]
    )
    usage = {
        key: sum(case["run"]["usage"][key] for case in cases)
        for key in ("llm_calls", "prompt_tokens", "cached_tokens", "output_tokens", "total_tokens")
    }
    configs = [case["config"] for case in cases]
    return {
        "case_count": len(cases),
        "mechanisms": mechanisms,
        "directions": directions,
        "complete_paths": complete_paths,
        "execution": {
            "rounds": sum(case["run"]["rounds"] for case in cases),
            "reactions": sum(case["run"]["reactions"] for case in cases),
            "usage": usage,
            "terminations": dict(Counter(case["run"]["termination"] for case in cases)),
        },
        "setup": {
            "models": config_values(configs, ("model", "name")),
            "cache_system_prompts": config_values(
                configs, ("model", "cache_system_prompts")
            ),
            "temperatures": config_values(configs, ("generation", "temperature")),
            "max_output_tokens": config_values(
                configs, ("generation", "max_output_tokens")
            ),
            "body_definitions": config_values(configs, ("body", "definition")),
            "shared_definitions": config_values(configs, ("body", "shared")),
            "meta_agent_enabled": config_values(configs, ("meta_agent", "enabled")),
            "router_modes": config_values(configs, ("routing", "mode")),
            "max_rounds": config_values(configs, ("simulation", "max_rounds")),
            "max_llm_calls": config_values(
                configs, ("simulation", "max_llm_calls")
            ),
        },
        "cases": [
            {
                "scenario_id": case["scenario_id"],
                "termination": case["run"]["termination"],
                "rounds": case["run"]["rounds"],
                "reactions": case["run"]["reactions"],
                "llm_calls": case["run"]["usage"]["llm_calls"],
                "total_tokens": case["run"]["usage"]["total_tokens"],
                "mechanisms": case["evaluation"]["mechanisms"],
                "directions": case["evaluation"]["directions"],
                "complete_paths": case["evaluation"]["complete_paths"],
            }
            for case in cases
        ],
    }


def summarize(batch_dir):
    arms = {
        arm_dir.name: summarize_arm(arm_dir)
        for arm_dir in sorted(path for path in batch_dir.iterdir() if path.is_dir())
    }
    scenario_sets = {
        arm: {case["scenario_id"] for case in result["cases"]}
        for arm, result in arms.items()
    }
    if len({frozenset(scenarios) for scenarios in scenario_sets.values()}) != 1:
        raise ValueError("arms do not contain the same scenarios")
    return {"batch_dir": str(batch_dir), "arms": arms}


def format_rate(value):
    return "n/a" if value is None else f"{value:.3f}"


def format_values(values):
    return ", ".join(values)


def display_arm(arm):
    return arm.replace("_", " ")


def conclusion(summary):
    arms = summary["arms"]
    strongest = max(arms, key=lambda arm: arms[arm]["mechanisms"]["f1"])
    cheapest = min(arms, key=lambda arm: arms[arm]["execution"]["usage"]["total_tokens"])
    strongest_result = arms[strongest]
    cheapest_result = arms[cheapest]
    lines = [
        f"`{display_arm(strongest)}` has the highest mechanism F1 "
        f"({strongest_result['mechanisms']['f1']:.3f}).",
        f"`{display_arm(cheapest)}` uses the fewest total tokens "
        f"({cheapest_result['execution']['usage']['total_tokens']:,}).",
    ]
    if "no_meta_llm" in arms and strongest != "no_meta_llm":
        baseline = arms["no_meta_llm"]
        lines.append(
            f"Against `no meta llm`, `{display_arm(strongest)}` improves mechanism F1 "
            f"by {strongest_result['mechanisms']['f1'] - baseline['mechanisms']['f1']:.3f} "
            f"while using {baseline['execution']['usage']['total_tokens'] - strongest_result['execution']['usage']['total_tokens']:,} fewer tokens."
        )
    return lines


def render(summary):
    rows = []
    setup_rows = []
    execution_rows = []
    for arm, result in summary["arms"].items():
        mechanisms = result["mechanisms"]
        directions = result["directions"]
        paths = result["complete_paths"]
        execution = result["execution"]
        rows.append(
            f"| {display_arm(arm)} | {result['case_count']} | "
            f"{format_rate(mechanisms['precision'])} | {format_rate(mechanisms['recall'])} | "
            f"{format_rate(mechanisms['f1'])} | "
            f"{mechanisms['tp']} / {mechanisms['fp']} / {mechanisms['fn']} | "
            f"{format_rate(directions['accuracy'])} ({directions['correct']}/{directions['evaluated']}) | "
            f"{format_rate(paths['recall'])} ({paths['recovered']}/{paths['total']}) | "
            f"{execution['usage']['llm_calls']} | {execution['usage']['total_tokens']:,} |"
        )
        setup = result["setup"]
        setup_rows.append(
            f"| {display_arm(arm)} | {format_values(setup['meta_agent_enabled'])} | "
            f"{format_values(setup['router_modes'])} | {format_values(setup['body_definitions'])} |"
        )
        execution_rows.append(
            f"| {display_arm(arm)} | {execution['rounds']} | {execution['reactions']} | "
            f"{', '.join(f'{name}: {count}' for name, count in sorted(execution['terminations'].items()))} |"
        )
    first_setup = next(iter(summary["arms"].values()))["setup"]
    return "\n".join(
        [
            "# Experiment Comparison",
            "",
            f"Batch: `{summary['batch_dir']}`",
            "",
            "## Setup",
            "",
            f"All arms contain the same {next(iter(summary['arms'].values()))['case_count']} scenarios. "
            f"Model: `{format_values(first_setup['models'])}`; temperature: `{format_values(first_setup['temperatures'])}`; "
            f"system-prompt cache: `{format_values(first_setup['cache_system_prompts'])}`; "
            f"maximum rounds: `{format_values(first_setup['max_rounds'])}`; maximum LLM calls per case: `{format_values(first_setup['max_llm_calls'])}`.",
            "",
            "| Arm | Meta Agent | Router | Body definition recorded in run config |",
            "|---|---:|---|---|",
            *setup_rows,
            "",
            "## Evaluation metrics",
            "",
            "Mechanism precision, recall, and F1 are micro-aggregated over unsigned agent-variable edges. Direction accuracy is evaluated only on recovered mechanisms and requires matching signed transitions. Complete-path recall is the fraction of GT input-to-terminal causal paths fully reconstructed.",
            "",
            "## Results",
            "",
            "| Arm | Cases | Mechanism precision | Mechanism recall | Mechanism F1 | Mechanism TP / FP / FN | Direction accuracy | Complete-path recall | LLM calls | Total tokens |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            *rows,
            "",
            "## Execution",
            "",
            "| Arm | Total rounds | Reactions | Terminations |",
            "|---|---:|---:|---|",
            *execution_rows,
            "",
            "## Conclusion",
            "",
            *conclusion(summary),
            "",
        ]
    )


def main():
    parser = argparse.ArgumentParser(description="Summarize completed experiment arms")
    parser.add_argument("--batch-dir", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    summary = summarize(args.batch_dir)
    args.summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    args.report.write_text(render(summary), encoding="utf-8")


if __name__ == "__main__":
    main()
