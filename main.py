import argparse
from pathlib import Path

import yaml

from src import router
from src.body import Body
from src.llm import LLM
from src.report import build
from src.runner import Runner
from src.schemas import Event, PathwayGraph, Vocabulary
from src.tracker import Tracker

ROOT = Path(__file__).parent


def load_yaml(path):
    return yaml.safe_load((ROOT / path).read_text())


def main():
    parser = argparse.ArgumentParser(description="Hierarchical physiological agent simulation")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    args = parser.parse_args()

    run_config = load_yaml(args.config)
    vocabulary_mode = run_config["agent"]["vocabulary_mode"]
    if vocabulary_mode not in {"constrained", "open"}:
        raise ValueError(
            f"unknown agent vocabulary mode '{vocabulary_mode}'; "
            "expected 'constrained' or 'open'"
        )
    enforce_vocabulary = vocabulary_mode == "constrained"
    vocabulary = Vocabulary.model_validate(load_yaml(run_config["vocabulary"]))
    ground_truth = PathwayGraph.model_validate_json(args.ground_truth.read_text())
    vocabulary.validate_graph(ground_truth)
    if len(ground_truth.input_event_ids) != 1:
        raise ValueError("the current runner requires exactly one input event")

    body_config = run_config["body"]
    llm = LLM(run_config)
    body = Body(
        load_yaml(body_config["definition"]),
        vocabulary,
        llm,
        ROOT / body_config["knowledge"],
        vocabulary_mode,
    )
    dispatcher = router.build(run_config["routing"], llm, body)
    tracker = Tracker(
        run_config,
        ROOT,
        dispatcher,
        ground_truth.scenario_id,
        vocabulary,
        enforce_vocabulary,
    )
    runner = Runner(
        dispatcher,
        tracker,
        llm,
        run_config["simulation"],
        enforce_vocabulary,
    )

    events_by_id = {event.id: event for event in ground_truth.events}
    specification = events_by_id[ground_truth.input_event_ids[0]]
    perturbation = Event(
        id="e0",
        agent_id=specification.agent_id,
        variable=specification.variable,
        level=specification.level,
        type="input",
        caused_by=None,
        round=0,
        generated_by="ground_truth_input",
    )
    termination = runner.run(perturbation)

    tracker.print_summary(termination)
    run_dir = tracker.save(run_config, termination)
    if run_config["debug"]["save_trace"]:
        print(f"Report: {build(run_dir)}")


if __name__ == "__main__":
    main()
