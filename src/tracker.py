import json
from datetime import datetime

import yaml

from src.pathway import build, longest_chain, signed


class Tracker:
    def __init__(
        self,
        config,
        root,
        router,
        scenario_id,
        vocabulary,
        validate_vocabulary,
    ):
        self.debug = config["debug"]
        self.run_dir = root / config["output"]["directory"] / datetime.now().strftime("%Y%m%d/%H%M%S")
        self.router = router
        self.scenario_id = scenario_id
        self.vocabulary = vocabulary
        self.validate_vocabulary = validate_vocabulary
        self.events = []
        self.rounds = []
        self.records = []
        self._pathway = None

    def begin(self, perturbation):
        self.events.append(perturbation)

    def begin_round(self, index, bundles, dropped, closures, routing):
        batches = sorted(bundles.items(), key=lambda batch: batch[0].id)
        entry = {
            "round": index,
            "dispatch": {
                leaf.id: [event.trace_dump() for event in events]
                for leaf, events in batches
            },
            "dropped": [event.trace_dump() for event in dropped],
            "homeostatic_closures": [event.trace_dump() for event in closures],
            "routing": [completion.dump() for completion in routing],
        }
        self.rounds.append(entry)
        if self.debug["verbose"]:
            self._print_dispatch(entry)

    def record(self, index, leaf, incoming, emitted, trace):
        entry = {
            "round": index,
            "agent": leaf.id,
            "incoming": [event.trace_dump() for event in incoming],
            "events": [event.trace_dump() for event in emitted],
            "trace": trace.dump() if trace else None,
        }
        self.events.extend(emitted)
        self.records.append(entry)
        if self.debug["verbose"]:
            self._print_record(entry)

    @property
    def pathway(self):
        if self._pathway is None:
            self._pathway = build(
                self.scenario_id,
                self.events,
                self.vocabulary,
                self.validate_vocabulary,
            )
        return self._pathway

    @property
    def usage(self):
        reasoning = [entry["trace"] for entry in self.records if entry["trace"]]
        routing = [call for entry in self.rounds for call in entry["routing"]]
        calls = reasoning + routing
        return {
            "reasoning_calls": len(reasoning),
            "routing_calls": len(routing),
            "prompt_tokens": sum(call["prompt_tokens"] for call in calls),
            "cached_tokens": sum(call["cached_tokens"] for call in calls),
            "output_tokens": sum(call["output_tokens"] for call in calls),
            "total_tokens": sum(call["total_tokens"] for call in calls),
            "max_tokens_per_call": max((call["total_tokens"] for call in calls), default=0),
        }

    def print_summary(self, termination):
        events_by_id = {event["id"]: event for event in self.pathway["events"]}
        print("\n=== EVENT PATHWAY ===\n")
        for edge in self.pathway["edges"]:
            source = events_by_id[edge["source"]]
            target = events_by_id[edge["target"]]
            print(f"{self._render(source)} → {self._render(target)}")

        chain = longest_chain(self.pathway)
        if chain:
            print("\nLongest chain:\n")
            print("\n→ ".join(self._render(events_by_id[event_id]) for event_id in chain))

        for failure in self.router.failures:
            print(f"\nRouting retry after: {failure}")

        usage = self.usage
        print(f"\nTermination: {termination}")
        print(f"Rounds: {len(self.rounds)}   Reactions: {len(self.records)}")
        print(f"LLM calls: reasoning={usage['reasoning_calls']}  routing={usage['routing_calls']}")
        print(f"Tokens: {usage['total_tokens']}   cached: {usage['cached_tokens']}"
              f"   max/call: {usage['max_tokens_per_call']}")

    def save(self, run_config, termination):
        if not self.debug["save_trace"]:
            return self.run_dir
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self._write("trace.json", {"rounds": self.rounds, "records": self.records})
        self._write("pathway.json", self.pathway)
        self._write("run.json", {
            "scenario_id": self.scenario_id,
            "model": run_config["model"]["name"],
            "termination": termination,
            "routing_failures": self.router.failures,
            "rounds": len(self.rounds),
            "reactions": len(self.records),
            "usage": self.usage,
        })
        (self.run_dir / "run_config.yaml").write_text(yaml.safe_dump(run_config, sort_keys=False))
        print(f"\nSaved to {self.run_dir}")
        return self.run_dir

    def _write(self, name, payload):
        (self.run_dir / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False))

    def _print_dispatch(self, entry):
        print(f"\n{'=' * 70}\nROUND {entry['round']}\n{'=' * 70}")
        for agent, events in entry["dispatch"].items():
            print(f"\n{agent} ←")
            for event in events:
                print(f"    {event['id']}  {self._render(event)}")
        for event in entry["dropped"]:
            print(f"\ndropped (unrouted): {self._render(event)}")
        for event in entry["homeostatic_closures"]:
            print(f"\nhomeostatic closure: {self._render(event)}")

    def _print_record(self, entry):
        print(f"\n[{entry['agent']}] emits")
        for event in entry["events"]:
            print(f"    {event['id']}  {self._render(event)} ← {event['caused_by']}")

    @staticmethod
    def _render(event):
        return f"{event['agent_id']}.{signed(event['variable'], event['level'])}"
