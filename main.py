import argparse
from pathlib import Path

import yaml

from src.body import Body
from src.llm import LLM
from src.report import build
from src import router
from src.runner import Runner
from src.schemas import Event
from src.tracker import Tracker

ROOT = Path(__file__).parent


def load(path):
    return yaml.safe_load((ROOT / path).read_text())


def main():
    parser = argparse.ArgumentParser(description="Hierarchical physiological agent simulation")
    parser.add_argument("--variable", required=True)
    parser.add_argument("--level", required=True, choices=["decreased", "increased"])
    args = parser.parse_args()

    run_config = load("config/run.yaml")

    body_config = run_config["body"]

    llm = LLM(run_config)
    body = Body(load(body_config["definition"]), llm, ROOT / body_config["knowledge"])
    dispatcher = router.build(run_config["routing"], llm, body)
    tracker = Tracker(run_config, ROOT, body, dispatcher)
    runner = Runner(body, dispatcher, tracker, llm, run_config["simulation"])

    perturbation = Event(args.variable, args.level, "perturbation", (), 0)
    termination = runner.run(perturbation)

    tracker.print_summary(termination)
    run_dir = tracker.save(run_config, termination)
    if run_config["debug"]["save_trace"]:
        print(f"Report: {build(run_dir)}")


if __name__ == "__main__":
    main()
