import json
from datetime import datetime

import yaml

from src.pathway import build, longest_chain, signed


class Tracker:
    def __init__(
        self,
        config,
        root,
        scenario_id,
        schema,
    ):
        self.debug = config["debug"]
        self.run_dir = root / config["output"]["directory"] / datetime.now().strftime("%Y%m%d/%H%M%S")
        self.scenario_id = scenario_id
        self.schema = schema
        self.events = {}
        self.rounds = []
        self.records = []

    def begin(self, perturbation):
        self.events[perturbation.id] = perturbation

    def begin_round(self, index, bundles, dropped, closures):
        batches = sorted(bundles.items(), key=lambda batch: batch[0].id)
        entry = {
            "round": index,
            "dispatch": {
                leaf.id: [event.id for event in events]
                for leaf, events in batches
            },
            "dropped": [event.id for event in dropped],
            "homeostatic_closures": [event.id for event in closures],
        }
        self.rounds.append(entry)
        if self.debug["verbose"]:
            self._print_dispatch(entry)

    def record(self, index, leaf, incoming, emitted, trace):
        entry = {
            "round": index,
            "agent": leaf.id,
            "incoming": [event.id for event in incoming],
            "events": [event.id for event in emitted],
            "trace": trace.dump() if trace else None,
        }
        self.events.update((event.id, event) for event in emitted)
        self.records.append(entry)
        if self.debug["verbose"]:
            self._print_record(entry)

    @property
    def pathway(self):
        return build(
            self.scenario_id,
            list(self.events.values()),
            self.schema,
        )

    @property
    def usage(self):
        calls = [entry["trace"] for entry in self.records if entry["trace"]]
        return {
            "llm_calls": len(calls),
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

        usage = self.usage
        print(f"\nTermination: {termination}")
        print(f"Rounds: {len(self.rounds)}   Reactions: {len(self.records)}")
        print(f"LLM calls: {usage['llm_calls']}")
        print(f"Tokens: {usage['total_tokens']}   cached: {usage['cached_tokens']}"
              f"   max/call: {usage['max_tokens_per_call']}")

    def save(self, run_config, termination):
        self.run_dir.mkdir(parents=True, exist_ok=True)

        if self.debug["save_trace"]:
            self._write("trace.json", {
                "events": [event.trace_dump() for event in self.events.values()],
                "rounds": self.rounds,
                "records": self.records,
            })
        self._write("pathway.json", self.pathway)
        self._write("run.json", {
            "scenario_id": self.scenario_id,
            "model": run_config["model"]["name"],
            "termination": termination,
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
        for agent, event_ids in entry["dispatch"].items():
            print(f"\n{agent} ←")
            for event_id in event_ids:
                event = self.events[event_id].trace_dump()
                print(f"    {event['id']}  {self._render(event)}")
        for event_id in entry["dropped"]:
            event = self.events[event_id].trace_dump()
            print(f"\ndropped (unrouted): {self._render(event)}")
        for event_id in entry["homeostatic_closures"]:
            event = self.events[event_id].trace_dump()
            print(f"\nhomeostatic closure: {self._render(event)}")

    def _print_record(self, entry):
        print(f"\n[{entry['agent']}] emits")
        for event_id in entry["events"]:
            event = self.events[event_id].trace_dump()
            print(f"    {event['id']}  {self._render(event)} ← {event['caused_by']}")

    @staticmethod
    def _render(event):
        return f"{event['agent_id']}.{signed(event['variable'], event['level'])}"
