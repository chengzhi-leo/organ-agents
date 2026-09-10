import json
from dataclasses import dataclass

from src.schemas import Completion, routing_model

ROUTER_SYSTEM_PROMPT = """
You route a batch of physiological events to their direct local recipients.

For each input event, select the smallest set of available agents for which this exact event can directly cause a local physiological response in the next single causal step.

Use each agent's owned_variables as its local response space. Select an agent when the input event can directly change at least one of those variables in the next causal step.

A direct local response may occur within the source agent itself. Include the source agent when the event can directly cause another local change in that same agent. Do not assume that an event emitted by an agent has completed all local causal processing.

Preserve causal intermediates. Never route an event directly to a downstream agent by skipping a required intermediate signal.

Treat each event independently. An event may be routed to zero, one, or multiple agents. Prefer an empty agent_ids list over speculative routing.

Return exactly one route for every input event.
Preserve each event_id exactly as provided.
Do not omit, duplicate, merge, or invent events.
Select agent_ids only from the available agents.
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
            f"- {agent.id}\n"
            f"  description: {agent.description}\n"
            f"  owned_variables: {', '.join(agent.owned_variables)}"
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
