import json
from datetime import datetime

import yaml

from src.pathway import build, signed


class Tracker:
    def __init__(self, config, root, body, router):
        self.debug = config["debug"]
        self.run_dir = root / config["output"]["directory"] / datetime.now().strftime("%Y%m%d/%H%M%S")
        self.body = body
        self.router = router
        self.registry = set(body.registry)
        self.perturbation = None
        self.rounds = []
        self.records = []
        self._pathway = None

    def begin(self, perturbation):
        self.perturbation = perturbation.dump()

    def begin_round(self, index, bundles, dropped, routing):
        batches = sorted(bundles.items(), key=lambda batch: batch[0].id)
        entry = {
            "round": index,
            "dispatch": {leaf.id: [event.dump() for event in events] for leaf, events in batches},
            "dropped": [event.dump() for event in dropped],
            "routing": [completion.dump() for completion in routing],
        }
        self.rounds.append(entry)
        if self.debug["verbose"]:
            self._print_dispatch(entry)

    def record(self, index, leaf, incoming, completion):
        arriving = {event.variable for event in incoming}
        effects = [effect.model_dump() for effect in completion.value.effects]
        cited = {cause for effect in effects for cause in effect["caused_by"]}
        resolvable = arriving | {effect["variable"] for effect in effects}
        entry = {
            "round": index,
            "agent": leaf.id,
            "incoming": [event.dump() for event in incoming],
            "effects": effects,
            "introduced_causes": sorted(cited - resolvable),
            "coined": sorted({effect["variable"] for effect in effects} - self.registry),
            "call": completion.dump(),
        }
        self.records.append(entry)
        if self.debug["verbose"]:
            self._print_record(entry)

    @property
    def pathway(self):
        if self._pathway is None:
            self._pathway = build(self.records, self.perturbation)
        return self._pathway

    @property
    def coined(self):
        return sorted({name for entry in self.records for name in entry["coined"]})

    @property
    def usage(self):
        reasoning = [entry["call"] for entry in self.records]
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
        print("\n=== VARIABLE PATHWAY ===\n")
        for edge in self.pathway["variable_edges"]:
            print(
                f"{signed(edge['from'], edge['from_level'])}"
                f" → {signed(edge['to'], edge['to_level'])}"
                f"   ({edge['agent']}, round {edge['round']})"
            )

        print("\n=== AGENT PATHWAY ===\n")
        for edge in self.pathway["agent_edges"]:
            print(f"{edge['from']} → {edge['to']}   via {', '.join(edge['via'])}")

        chain = self.pathway["longest_chain"]
        if chain:
            print("\nLongest chain:\n")
            print("\n→ ".join(signed(variable, level) for variable, level in chain))

        if self.coined:
            print(f"\nCoined variables: {', '.join(self.coined)}")

        if self.router.audit:
            print("\nRouting audit:\n")
            for entry in self.router.audit:
                print(
                    f"    {entry['status']:11s} {signed(entry['variable'], entry['level'])}"
                    f" → {entry['agent']}"
                )
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
            "perturbation": self.perturbation,
            "model": run_config["model"]["name"],
            "termination": termination,
            "routing_mode": self.router.mode,
            "routing_audit": self.router.audit,
            "routing_failures": self.router.failures,
            "rounds": len(self.rounds),
            "reactions": len(self.records),
            "usage": self.usage,
            "coined": self.coined,
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
                print(f"    {signed(event['variable'], event['level'])}   (from {event['source_agent']})")
        for event in entry["dropped"]:
            print(f"\ndropped (unrouted): {signed(event['variable'], event['level'])}")

    def _print_record(self, entry):
        print(f"\n[{entry['agent']}] emits")
        for effect in entry["effects"]:
            print(f"    {signed(effect['variable'], effect['level'])}   ← {', '.join(effect['caused_by'])}")
        if entry["introduced_causes"]:
            print(f"    introduced causes: {', '.join(entry['introduced_causes'])}")
        if entry["coined"]:
            print(f"    coined: {', '.join(entry['coined'])}")
