import json
from dataclasses import dataclass

from src.schemas import Completion, routing_model

ROUTER_SYSTEM_PROMPT = """
You route a batch of physiological events to locally relevant components.

For each input event, select every available agent that may directly perceive or locally respond to that event.

Treat each event independently. An event may be routed to zero, one, or multiple agents.

Return exactly one route for every input event.
Preserve each event_id exactly as provided.
Do not omit, duplicate, merge, or invent events.
Select agent_ids only from the available agents.
Use an empty agent_ids list when no available agent is relevant.
The top-level object must contain only routes. Each route must contain only event_id and agent_ids.

Do not predict physiological effects, variables, directions, mechanisms, or downstream events. Route each event as-is.

Return JSON only in the following format:

{
  "routes": [
    {
      "event_id": "<input event_id>",
      "agent_ids": ["<available agent id>"]
    }
  ]
}

"""


@dataclass
class RoutingDecision:
    event_id: str
    agents: list

    def dump(self):
        return {
            "event": self.event_id,
            "selected_agents": [agent.id for agent in self.agents],
        }


@dataclass
class Routing:
    routes: dict
    decisions: list[RoutingDecision]
    trace: Completion | None


class RuleBasedRouter:
    def __init__(self, body):
        self.agents = body.agents
        self.schema = body.schema

    def required_calls(self, events):
        return 0

    def route(self, events):
        decisions = [
            RoutingDecision(
                event.id,
                [
                    agent
                    for agent in self.agents
                    if event.variable in self.schema.agents[agent.id].inputs
                ],
            )
            for event in events
        ]
        return Routing(
            {decision.event_id: decision.agents for decision in decisions},
            decisions,
            None,
        )


class LLMRouter:
    def __init__(self, body, llm):
        self.agents = body.agents
        self.agents_by_id = {agent.id: agent for agent in self.agents}
        self.llm = llm
        catalog = "\n".join(
            f"- {agent.id}: {agent.description}"
            for agent in self.agents
        )
        self.system_prompt = f"{ROUTER_SYSTEM_PROMPT}\nAvailable agents:\n{catalog}"

    def required_calls(self, events):
        return int(bool(events and self.agents))

    def route(self, events):
        if not events:
            return Routing({}, [], None)
        if not self.agents:
            decisions = [RoutingDecision(event.id, []) for event in events]
            return Routing(
                {decision.event_id: decision.agents for decision in decisions},
                decisions,
                None,
            )

        event_ids = [event.id for event in events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("LLM router received duplicate event IDs")

        prompt = json.dumps({
            "events": [
                {
                    "event_id": event.id,
                    "source_component": event.agent_id,
                    "variable": event.variable,
                    "level": event.level,
                }
                for event in events
            ]
        }, indent=2)
        completion = self.llm.generate(
            self.system_prompt,
            prompt,
            routing_model(event_ids, list(self.agents_by_id)),
        )
        routes = self._validate_routes(event_ids, completion.value.routes)
        decisions = [
            RoutingDecision(
                event_id,
                self._resolve_agents(routes[event_id].agent_ids),
            )
            for event_id in event_ids
        ]
        return Routing(
            {decision.event_id: decision.agents for decision in decisions},
            decisions,
            completion,
        )

    @staticmethod
    def _validate_routes(event_ids, routes):
        returned_ids = [route.event_id for route in routes]
        if len(returned_ids) != len(set(returned_ids)):
            raise ValueError("LLM router returned duplicate event IDs")
        missing = set(event_ids) - set(returned_ids)
        unexpected = set(returned_ids) - set(event_ids)
        if missing or unexpected:
            raise ValueError(
                f"LLM router event mismatch: missing={sorted(missing)}, "
                f"unexpected={sorted(unexpected)}"
            )
        for route in routes:
            if len(route.agent_ids) != len(set(route.agent_ids)):
                raise ValueError(
                    f"LLM router returned duplicate agent IDs for event '{route.event_id}'"
                )
        return {route.event_id: route for route in routes}

    def _resolve_agents(self, agent_ids):
        selected = set(agent_ids)
        return [agent for agent in self.agents if agent.id in selected]


def build(body, llm, config):
    mode = config["mode"]
    if mode == "rule_based":
        return RuleBasedRouter(body)
    if mode == "llm":
        return LLMRouter(body, llm)
    raise ValueError(f"unknown router mode '{mode}'")
