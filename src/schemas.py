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


def changes_model(agent_id, owned_variables):
    if not owned_variables:
        raise ValueError(f"agent '{agent_id}' has no owned variables")
    variable = Literal.__getitem__(tuple(owned_variables))
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


def routing_model(event_ids, agent_ids):
    if not event_ids:
        raise ValueError("LLM router requires at least one event")
    if not agent_ids:
        raise ValueError("LLM router requires at least one available agent")
    event_id = Literal.__getitem__(tuple(event_ids))
    agent_id = Literal.__getitem__(tuple(agent_ids))
    route = create_model(
        "routing_route",
        __base__=StrictModel,
        event_id=(event_id, ...),
        agent_ids=(list[agent_id], ...),
    )
    return create_model(
        "routing",
        __base__=StrictModel,
        routes=(list[route], ...),
    )


def agent_selection_model(agent_ids):
    if not agent_ids:
        raise ValueError("agent selection requires at least one available agent")
    agent_id = Literal.__getitem__(tuple(agent_ids))
    return create_model(
        "agent_selection",
        __base__=StrictModel,
        agents=(list[agent_id], ...),
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
    required_agents: list[str] | None = None

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
    description: str
    knowledge: str
    inputs: list[str]
    owned_variables: list[str]


class BloodTransform(StrictModel):
    source: str
    target: str
    direction: Literal["same", "opposite"]


class BloodInterface(StrictModel):
    owned_variables: list[str]
    transforms: list[BloodTransform]

    @property
    def inputs(self):
        return [transform.source for transform in self.transforms]


class SystemSchema(StrictModel):
    external_sources: dict[str, list[str]]
    agents: dict[str, AgentInterface]
    blood: BloodInterface

    @classmethod
    def compose(cls, definitions):
        schema = {}
        for definition in definitions:
            if not isinstance(definition, dict):
                raise ValueError("schema definitions must be YAML mappings")
            duplicate_sections = schema.keys() & definition.keys()
            if duplicate_sections:
                raise ValueError(
                    f"schema sections are defined more than once: {sorted(duplicate_sections)}"
                )
            schema.update(definition)
        return cls.model_validate(schema)

    @model_validator(mode="after")
    def validate_definitions(self):
        if not self.agents:
            raise ValueError("schema must define at least one agent")
        if "blood" in self.agents:
            raise ValueError("blood must be defined as the shared compartment")
        reserved = self.external_sources.keys() & ({"blood"} | self.agents.keys())
        if reserved:
            raise ValueError(
                f"external source IDs conflict with body components: {sorted(reserved)}"
            )
        for source_id, variables in self.external_sources.items():
            if not variables:
                raise ValueError(f"external source '{source_id}' must declare variables")
            if len(variables) != len(set(variables)):
                raise ValueError(f"external source '{source_id}' declares duplicate variables")
        for agent_id, interface in self.agents.items():
            for field in ("inputs", "owned_variables"):
                variables = getattr(interface, field)
                if len(variables) != len(set(variables)):
                    raise ValueError(f"agent '{agent_id}' declares duplicate {field}")
            if not interface.owned_variables:
                raise ValueError(f"agent '{agent_id}' must own at least one variable")

        if not self.blood.owned_variables:
            raise ValueError("blood must own at least one variable")
        if len(self.blood.owned_variables) != len(set(self.blood.owned_variables)):
            raise ValueError("blood declares duplicate owned_variables")
        if not self.blood.transforms:
            raise ValueError("blood must declare at least one transform")
        sources = self.blood.inputs
        if len(sources) != len(set(sources)):
            raise ValueError("blood declares duplicate transform sources")
        for transform in self.blood.transforms:
            if transform.target not in self.blood.owned_variables:
                raise ValueError(
                    f"blood transform target '{transform.target}' is not owned by blood"
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
            location = f"event '{event.id}'"
            if event.type == "input":
                self.validate_perturbation(event.agent_id, event.variable, location)
            else:
                self.validate_owned_variable(event.agent_id, event.variable, location)
        events = {event.id: event for event in graph.events}
        for edge in graph.edges:
            source = events[edge.source]
            target = events[edge.target]
            if target.agent_id == "blood":
                self.validate_translation(
                    source,
                    target,
                    f"edge '{edge.source} -> {edge.target}'",
                )
        return graph

    def validate_translation(self, source, target, location):
        transforms = {
            transform.source: transform
            for transform in self.blood.transforms
        }
        if source.variable not in transforms:
            raise ValueError(
                f"{location} source variable '{source.variable}' has no blood transform"
            )
        transform = transforms[source.variable]
        if target.variable != transform.target:
            raise ValueError(
                f"{location} target variable '{target.variable}' does not match blood "
                f"transform target '{transform.target}'"
            )
        expected_level = source.level if transform.direction == "same" else FLIP[source.level]
        if target.level != expected_level:
            raise ValueError(
                f"{location} target level '{target.level}' does not match blood transform "
                f"direction '{transform.direction}'"
            )

    def validate_input(self, agent_id, variable, location):
        self._validate(agent_id, variable, "inputs", location)

    def validate_owned_variable(self, agent_id, variable, location):
        self._validate(agent_id, variable, "owned_variables", location)

    def validate_perturbation(self, component_id, variable, location):
        if component_id not in self.external_sources:
            self.validate_owned_variable(component_id, variable, location)
            return
        if variable not in self.external_sources[component_id]:
            raise ValueError(
                f"{location} variable '{variable}' is not declared by external source "
                f"'{component_id}'"
            )

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
    trace: Completion


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
