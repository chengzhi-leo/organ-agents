from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, create_model, model_validator

Level = Literal["decreased", "increased"]
EventType = Literal["input", "response"]

FLIP = {"increased": "decreased", "decreased": "increased"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Change(StrictModel):
    variable: str
    level: Level
    caused_by: str


class Changes(StrictModel):
    changes: list[Change]


def constrained_changes_model(agent_id, variables):
    if not variables:
        raise ValueError(f"agent '{agent_id}' has no output variables")
    variable = Literal.__getitem__(tuple(variables))
    change = create_model(
        f"{agent_id}_change",
        __base__=StrictModel,
        variable=(variable, ...),
        level=(Level, ...),
        caused_by=(str, ...),
    )
    return create_model(
        f"{agent_id}_changes",
        __base__=StrictModel,
        changes=(list[change], ...),
    )


class Assignment(StrictModel):
    change: str
    agent_ids: list[str]


class Dispatch(StrictModel):
    assignments: list[Assignment]


class GraphEvent(StrictModel):
    id: str
    agent_id: str
    variable: str
    level: Level
    type: EventType
    round: int | None = None
    generated_by: str | None = None


class GraphEdge(StrictModel):
    source: str
    target: str


class Source(StrictModel):
    document: str
    pages: list[int]
    line_ranges: list[str]
    evidence: str


class PathwayGraph(StrictModel):
    scenario_id: str
    input_event_ids: list[str]
    events: list[GraphEvent]
    edges: list[GraphEdge]
    source: Source | None = None

    @model_validator(mode="after")
    def validate_references(self):
        event_ids = [event.id for event in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("event IDs must be unique")

        known = set(event_ids)
        inputs = set(self.input_event_ids)
        if not inputs:
            raise ValueError("input_event_ids must not be empty")
        if unknown := inputs - known:
            raise ValueError(f"input_event_ids reference unknown events: {sorted(unknown)}")

        declared_inputs = {event.id for event in self.events if event.type == "input"}
        if inputs != declared_inputs:
            raise ValueError("input_event_ids must exactly match events with type 'input'")

        response_keys = [
            (event.agent_id, event.variable, event.level)
            for event in self.events
            if event.type == "response"
        ]
        if len(response_keys) != len(set(response_keys)):
            raise ValueError("response nodes must be unique by agent, variable, and level")

        edge_keys = []
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise ValueError(f"edge references unknown event: {edge.source} -> {edge.target}")
            if edge.source == edge.target:
                raise ValueError(f"self-edge is invalid: {edge.source} -> {edge.target}")
            edge_keys.append((edge.source, edge.target))
        if len(edge_keys) != len(set(edge_keys)):
            raise ValueError("graph edges must be unique")
        return self


class AgentVocabulary(StrictModel):
    kind: Literal[
        "translator_environment",
        "llm_agent",
        "source_placeholder",
        "input_only",
    ]
    variables: list[str]


class Vocabulary(StrictModel):
    levels: list[Level]
    agents: dict[str, AgentVocabulary]

    @model_validator(mode="after")
    def validate_definitions(self):
        if set(self.levels) != set(FLIP):
            raise ValueError("vocabulary levels must be exactly decreased and increased")
        for agent_id, agent in self.agents.items():
            if len(agent.variables) != len(set(agent.variables)):
                raise ValueError(f"agent '{agent_id}' declares duplicate variables")
        return self

    def validate_graph(self, graph):
        for event in graph.events:
            self.validate_owner(event.agent_id, event.variable, f"event '{event.id}'")
        return graph

    def validate_owner(self, agent_id, variable, location):
        if agent_id not in self.agents:
            raise ValueError(f"{location} references unknown agent '{agent_id}'")
        if variable not in self.agents[agent_id].variables:
            raise ValueError(
                f"{location} variable '{variable}' does not belong to agent '{agent_id}'"
            )


@dataclass
class Completion:
    value: object
    system_prompt: str
    prompt: str
    text: str
    prompt_tokens: int
    cached_tokens: int
    output_tokens: int
    total_tokens: int

    def dump(self):
        return {
            "system_prompt": self.system_prompt,
            "prompt": self.prompt,
            "response": self.text,
            "prompt_tokens": self.prompt_tokens,
            "cached_tokens": self.cached_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class Reaction:
    changes: list[Change]
    trace: Completion | None


class Event(GraphEvent):
    caused_by: str | None

    @property
    def key(self):
        return self.agent_id, self.variable, self.level

    def graph_dump(self):
        return self.model_dump(exclude={"caused_by"}, exclude_none=True)

    def trace_dump(self):
        return self.model_dump(exclude_none=False)
