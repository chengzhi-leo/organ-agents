import argparse
from pathlib import Path

import yaml

from src import router
from src.body import Body
from src.llm import LLM
from src.report import build
from src.runner import Runner
from src.schemas import Event, ScenarioInput, SystemSchema
from src.tracker import Tracker

ROOT = Path(__file__).parent


def load_yaml(path):
    return yaml.safe_load((ROOT / path).read_text())


def main():
    parser = argparse.ArgumentParser(description="Hierarchical physiological agent simulation")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()

    run_config = load_yaml(args.config)
    schema = SystemSchema.model_validate(load_yaml(run_config["schema"]))
    scenario = ScenarioInput.model_validate_json(args.input.read_text())
    schema.validate_output(
        scenario.agent_id,
        scenario.variable,
        f"scenario '{scenario.scenario_id}'",
    )

    body_config = run_config["body"]
    llm = LLM(run_config)
    body = Body(
        load_yaml(body_config["definition"]),
        schema,
        llm,
        ROOT / body_config["knowledge"],
    )
    dispatcher = router.build(body, run_config["routing"])
    tracker = Tracker(
        run_config,
        ROOT,
        scenario.scenario_id,
        schema,
    )
    runner = Runner(
        dispatcher,
        tracker,
        llm,
        run_config["simulation"],
    )

    perturbation = Event(
        id="e0",
        agent_id=scenario.agent_id,
        variable=scenario.variable,
        level=scenario.level,
        type="input",
        caused_by=None,
        round=0,
    )
    termination = runner.run(perturbation)

    tracker.print_summary(termination)
    run_dir = tracker.save(run_config, termination)
    if run_config["debug"]["save_trace"]:
        print(f"Report: {build(run_dir)}")


if __name__ == "__main__":
    main()
