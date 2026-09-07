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


def changes_model(agent_id, outputs):
    if not outputs:
        raise ValueError(f"agent '{agent_id}' has no output variables")
    variable = Literal.__getitem__(tuple(outputs))
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


class GraphEvent(StrictModel):
    id: str
    agent_id: str
    variable: str
    level: Level
    type: EventType


class ScenarioInput(StrictModel):
    scenario_id: str
    agent_id: str
    variable: str
    level: Level


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


class AgentInterface(StrictModel):
    inputs: list[str]
    outputs: list[str]


class BloodTransform(StrictModel):
    source: str
    target: str
    direction: Literal["same", "opposite"]


class BloodInterface(StrictModel):
    outputs: list[str]
    transforms: list[BloodTransform]

    @property
    def inputs(self):
        return [transform.source for transform in self.transforms]


class SystemSchema(StrictModel):
    agents: dict[str, AgentInterface]
    blood: BloodInterface

    @model_validator(mode="after")
    def validate_definitions(self):
        if not self.agents:
            raise ValueError("schema must define at least one agent")
        if "blood" in self.agents:
            raise ValueError("blood must be defined as the shared compartment")
        for agent_id, interface in self.agents.items():
            for field in ("inputs", "outputs"):
                variables = getattr(interface, field)
                if len(variables) != len(set(variables)):
                    raise ValueError(f"agent '{agent_id}' declares duplicate {field}")
            if not interface.outputs:
                raise ValueError(f"agent '{agent_id}' must declare at least one output")

        if not self.blood.outputs:
            raise ValueError("blood must declare at least one output")
        if len(self.blood.outputs) != len(set(self.blood.outputs)):
            raise ValueError("blood declares duplicate outputs")
        if not self.blood.transforms:
            raise ValueError("blood must declare at least one transform")
        sources = self.blood.inputs
        if len(sources) != len(set(sources)):
            raise ValueError("blood declares duplicate transform sources")
        producers = {
            variable
            for interface in self.agents.values()
            for variable in interface.outputs
        }
        for transform in self.blood.transforms:
            if transform.source not in producers:
                raise ValueError(
                    f"blood transform source '{transform.source}' has no agent producer"
                )
            if transform.target not in self.blood.outputs:
                raise ValueError(
                    f"blood transform target '{transform.target}' is not a blood output"
                )
        return self

    def interface(self, component_id):
        if component_id == "blood":
            return self.blood
        if component_id not in self.agents:
            raise ValueError(f"unknown component '{component_id}'")
        return self.agents[component_id]

    def validate_graph(self, graph):
        for event in graph.events:
            self.validate_output(event.agent_id, event.variable, f"event '{event.id}'")
        events = {event.id: event for event in graph.events}
        for edge in graph.edges:
            source = events[edge.source]
            target = events[edge.target]
            self.validate_input(
                target.agent_id,
                source.variable,
                f"edge '{edge.source} -> {edge.target}'",
            )
        return graph

    def validate_input(self, agent_id, variable, location):
        self._validate(agent_id, variable, "inputs", location)

    def validate_output(self, agent_id, variable, location):
        self._validate(agent_id, variable, "outputs", location)

    def _validate(self, agent_id, variable, field, location):
        try:
            interface = self.interface(agent_id)
        except ValueError:
            raise ValueError(f"{location} references unknown agent '{agent_id}'") from None
        if variable not in getattr(interface, field):
            raise ValueError(
                f"{location} variable '{variable}' is not in agent '{agent_id}' {field}"
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
    round: int

    @property
    def key(self):
        return self.agent_id, self.variable, self.level

    def graph_dump(self):
        return self.model_dump(exclude={"caused_by", "round"})

    def trace_dump(self):
        return self.model_dump(exclude_none=False)
