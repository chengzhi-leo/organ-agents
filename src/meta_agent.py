import json
from dataclasses import dataclass

from src.schemas import Completion, agent_selection_model

META_AGENT_SYSTEM_PROMPT = """
You select the local physiological agents that should participate in a simulation.

Given the initial physiological perturbation and the descriptions of all available local agents, select a focused but sufficiently complete agent set for representing the physiological response.

Include agents that are likely to play a meaningful role as:
- direct sensors or responders
- necessary signaling or endocrine relays
- major downstream targets or effectors
- major parallel branches or characteristic downstream handling components

Do not include agents that are only weakly, broadly, or tangentially related to the perturbation.

Do not output physiological effects, variables, directions, mechanisms, or causal pathways.

Select only agents from the available set and return each agent at most once.

Return JSON only:

{
  "agents": ["agent_id_1", "agent_id_2"]
}

Return an empty list if no available agent is relevant.
"""


@dataclass
class MetaSelection:
    agent_ids: list[str]
    trace: Completion

    def dump(self):
        return {
            "enabled": True,
            "selected_agents": self.agent_ids,
            "trace": self.trace.dump(),
        }


class MetaAgent:
    def __init__(self, agents, llm):
        self.agent_ids = list(agents)
        self.llm = llm
        catalog = "\n".join(
            f"- {agent_id}: {interface.description}"
            for agent_id, interface in agents.items()
        )
        self.system_prompt = f"{META_AGENT_SYSTEM_PROMPT}\nAvailable agents:\n{catalog}"

    def select(self, scenario):
        prompt = json.dumps(
            {
                "initial_perturbation": {
                    "source_component": scenario.agent_id,
                    "variable": scenario.variable,
                    "level": scenario.level,
                }
            },
            indent=2,
        )
        completion = self.llm.generate(
            self.system_prompt,
            prompt,
            agent_selection_model(self.agent_ids),
        )
        selected = completion.value.agents
        if len(selected) != len(set(selected)):
            raise ValueError("Meta Agent returned duplicate agent IDs")
        selected_set = set(selected)
        ordered = [agent_id for agent_id in self.agent_ids if agent_id in selected_set]
        return MetaSelection(ordered, completion)


def evaluate_selection(selected, expected):
    selected = set(selected)
    expected = set(expected)
    tp = len(selected & expected)
    fp = len(selected - expected)
    fn = len(expected - selected)
    metrics = selection_metrics(tp, fp, fn)
    return {**metrics, "exact_match": selected == expected}


def selection_metrics(tp, fp, fn):
    selected = tp + fp
    expected = tp + fn
    precision = tp / selected if selected else 0.0
    recall = tp / expected if expected else 0.0
    total = precision + recall
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / total if total else 0.0,
    }
