from src.schemas import Change, FLIP, Reaction, changes_model

BASE_SYSTEM_PROMPT = """
You represent one physiological organ or component.

Given the incoming events, report the direct physiological changes that occur locally within this component.

Rules:
- Perform only one causal step from the incoming events.
- Report only changes within this component.
- The provided local physiological knowledge is reliable but may be incomplete. Supplement it with your established physiological knowledge when necessary.
- Use only variables listed under Owned variables.
- Each change must be directly caused by exactly one incoming event and must cite its event ID.
- If no incoming event directly causes a change to an owned variable, return an empty changes list.

Return JSON only:

{"changes": [
  {
    "variable": str,
    "level": "decreased" | "increased",
    "caused_by": str
  }
]}
"""


class Agent:
    def __init__(self, id, description, knowledge, owned_variables, llm):
        self.id = id
        self.description = description
        self.knowledge = knowledge
        self.owned_variables = owned_variables
        self.llm = llm
        self.response_model = changes_model(id, owned_variables)

    def react(self, events):
        completion = self.llm.generate(
            BASE_SYSTEM_PROMPT,
            self._prompt(events),
            self.response_model,
        )
        return Reaction(completion.value.changes, completion)

    def _prompt(self, events):
        arriving = "\n".join(
            f"{event.id}: {event.agent_id}.{event.variable} = {event.level}"
            for event in events
        )
        prompt = (
            f"Your component: {self.id}\n"
            f"{self.description}\n\n"
            f"Your local physiological knowledge:\n{self.knowledge}\n\n"
            f"Owned variables:\n{', '.join(self.owned_variables)}\n\n"
        )
        return f"{prompt}Incoming events:\n{arriving}"


class BloodTranslator:
    id = "blood"

    def __init__(self, owned_variables, transforms):
        self.owned_variables = owned_variables
        self.transforms = {transform.source: transform for transform in transforms}

    def translate(self, event):
        transform = self.transforms.get(event.variable)
        if transform is None:
            return None
        level = event.level if transform.direction == "same" else FLIP[event.level]
        return Change(
            variable=transform.target,
            level=level,
            caused_by=event.id,
        )
