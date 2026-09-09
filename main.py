import argparse
from datetime import datetime
from pathlib import Path

import yaml

from src import router
from src.body import Body
from src.llm import LLM
from src.meta_agent import MetaAgent
from src.runner import Runner
from src.schemas import Event, ScenarioInput, SystemSchema
from utils.report import build
from utils.tracker import Tracker

ROOT = Path(__file__).parent


def load_yaml(path):
    return yaml.safe_load((ROOT / path).read_text())


def load_scenarios(paths, schema):
    scenarios = [ScenarioInput.model_validate_json(path.read_text()) for path in paths]
    scenario_ids = [scenario.scenario_id for scenario in scenarios]
    if len(scenario_ids) != len(set(scenario_ids)):
        raise ValueError("scenario IDs must be unique within one batch")
    for scenario in scenarios:
        schema.validate_perturbation(
            scenario.agent_id,
            scenario.variable,
            f"scenario '{scenario.scenario_id}'",
        )
    return scenarios


def run_scenario(run_config, schema, scenario, run_dir):
    body_config = run_config["body"]
    llm = LLM(run_config)
    meta_enabled = run_config["meta_agent"]["enabled"]
    if not isinstance(meta_enabled, bool):
        raise ValueError("meta_agent.enabled must be a boolean")
    meta_selection = MetaAgent(schema.agents, llm).select(scenario) if meta_enabled else None
    agent_ids = (
        meta_selection.agent_ids
        if meta_selection is not None
        else list(schema.agents)
    )
    body = Body(
        schema,
        llm,
        ROOT / body_config["knowledge"],
        agent_ids,
    )
    event_router = router.build(body, llm, run_config["routing"])
    tracker = Tracker(
        run_config,
        run_dir,
        scenario.scenario_id,
        schema,
        meta_selection,
    )
    runner = Runner(
        body.translator,
        event_router,
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

    pathway = tracker.pathway
    if tracker.usage["llm_calls"] != llm.call_count:
        raise RuntimeError("tracked LLM calls do not match the global LLM call counter")
    tracker.print_summary(pathway, termination)
    run_dir = tracker.save(run_config, pathway, termination)
    if run_config["debug"]["save_trace"]:
        print(f"Report: {build(run_dir)}")


def main():
    parser = argparse.ArgumentParser(description="Physiological agent pathway reconstruction")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--input", type=Path, nargs="+", required=True)
    parser.add_argument("--batch-id", type=Path)
    args = parser.parse_args()

    run_config = load_yaml(args.config)
    body_config = run_config["body"]
    schema = SystemSchema.compose([
        load_yaml(body_config["definition"]),
        load_yaml(body_config["shared"]),
    ])
    scenarios = load_scenarios(args.input, schema)
    batch_id = args.batch_id or Path(datetime.now().strftime("%Y%m%d/%H%M%S"))
    if batch_id.is_absolute() or ".." in batch_id.parts:
        raise ValueError("batch ID must be a relative path without '..'")
    batch_dir = ROOT / run_config["output"]["directory"] / batch_id
    arm = run_config["output"].get("arm")
    if arm:
        batch_dir /= arm
    for scenario in scenarios:
        run_scenario(run_config, schema, scenario, batch_dir / scenario.scenario_id)
    print(f"\nBatch saved to {batch_dir}")


if __name__ == "__main__":
    main()
