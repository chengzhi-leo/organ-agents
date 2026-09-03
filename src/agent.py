from src.schemas import Change, Changes, FLIP, Reaction, constrained_changes_model

BASE_SYSTEM_PROMPT = """You are one local physiological component in a distributed human physiology model.

An input is a new external or system-level perturbation. A response is a directional effect produced
by a physiological mechanism, not a new abnormal baseline state. All changes you report become
responses; the orchestrator assigns their event type.

For each incoming event, report only direct directional changes inside your own component. A change
with no local mechanism is ignored. Never emit a variable owned by another component.

Each change must cite exactly one incoming event ID as its immediate cause. Do not cite a variable,
an event that was not supplied, or another change in the same response. The orchestrator will assign
IDs to your changes and propagate them in later rounds.

{vocabulary_instruction}

Return JSON only:
{"changes": [{"variable": str, "level": "decreased" | "increased", "caused_by": str}]}
"""

VOCABULARY_INSTRUCTIONS = {
    "constrained": "Use exactly one of the allowed output variable names. Never invent new names.",
    "open": "Name each local change precisely using a concise snake_case variable name. You are not restricted to a predefined vocabulary.",
}


class Agent:
    uses_llm = True

    def __init__(self, id, description, knowledge, variables, llm, vocabulary_mode):
        if vocabulary_mode not in VOCABULARY_INSTRUCTIONS:
            raise ValueError(
                f"unknown agent vocabulary mode '{vocabulary_mode}'; "
                f"expected one of {sorted(VOCABULARY_INSTRUCTIONS)}"
            )
        self.id = id
        self.description = description
        self.knowledge = knowledge
        self.variables = variables
        self.llm = llm
        self.vocabulary_mode = vocabulary_mode
        self.response_model = (
            constrained_changes_model(id, variables)
            if vocabulary_mode == "constrained"
            else Changes
        )
        self.system_prompt = BASE_SYSTEM_PROMPT.replace(
            "{vocabulary_instruction}",
            VOCABULARY_INSTRUCTIONS[vocabulary_mode],
        )

    def react(self, events):
        completion = self.llm.generate(
            self.system_prompt,
            self._prompt(events),
            self.response_model,
        )
        return Reaction(completion.value.changes, completion)

    def _prompt(self, events):
        arriving = "\n".join(
            f"- {event.id} [{event.type}]: "
            f"{event.agent_id}.{event.variable} = {event.level}"
            for event in events
        )
        prompt = (
            f"Your component: {self.id}\n"
            f"{self.description}\n\n"
            f"Your local physiological knowledge:\n{self.knowledge}\n\n"
        )
        if self.vocabulary_mode == "constrained":
            prompt += f"Allowed output variables:\n{', '.join(self.variables)}\n\n"
        return f"{prompt}Incoming events:\n{arriving}"


class Blood:
    uses_llm = False

    def __init__(self, id, description, variables, transfers):
        self.id = id
        self.description = description
        self.variables = variables
        self.transfers = {
            (transfer["source"]["agent_id"], transfer["source"]["variable"]): transfer
            for transfer in transfers
        }

    def react(self, events):
        changes = []
        for event in events:
            transfer = self.transfers.get((event.agent_id, event.variable))
            if transfer is None:
                continue
            direction = transfer["direction"]
            if direction not in ("same", "opposite"):
                raise ValueError(f"blood transfer declares unknown direction '{direction}'")
            level = event.level if direction == "same" else FLIP[event.level]
            changes.append(Change(
                variable=transfer["target"]["variable"],
                level=level,
                caused_by=event.id,
            ))
        return Reaction(changes, None)
