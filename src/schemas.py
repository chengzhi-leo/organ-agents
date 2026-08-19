from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

Level = Literal["decreased", "increased"]
Relation = Literal["increases", "reduces"]


class Effect(BaseModel):
    variable: str
    level: Level
    caused_by: list[str]


class Reaction(BaseModel):
    effects: list[Effect]


class Assignment(BaseModel):
    change: str
    variable: str
    level: Level
    agent_ids: list[str]


class Dispatch(BaseModel):
    assignments: list[Assignment]


@dataclass(frozen=True)
class Link:
    source: str
    relation: Relation
    target: str


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
class Event:
    variable: str
    level: Level
    source_agent: str
    caused_by: tuple[str, ...]
    round: int

    @property
    def key(self):
        return self.variable, self.level

    def dump(self):
        return {
            "variable": self.variable,
            "level": self.level,
            "source_agent": self.source_agent,
            "caused_by": list(self.caused_by),
            "round": self.round,
        }
