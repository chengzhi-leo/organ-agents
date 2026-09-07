from src.schemas import Change, FLIP, Reaction, changes_model

BASE_SYSTEM_PROMPT = """
You represent one physiological organ or component.

Given the incoming events, report the direct physiological changes that occur locally within this component.

Rules:
- Perform only one causal step from the incoming events.
- Report only changes within this component.
- The provided local physiological knowledge is reliable but may be incomplete. Supplement it with your established physiological knowledge when necessary.
- Use only variables listed under Allowed output variables.
- Each change must be directly caused by exactly one incoming event and must cite its event ID.
- If no incoming event directly causes an allowed output, return an empty changes list.

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
    uses_llm = True

    def __init__(self, id, description, knowledge, inputs, outputs, llm):
        self.id = id
        self.description = description
        self.knowledge = knowledge
        self.inputs = inputs
        self.outputs = outputs
        self.llm = llm
        self.response_model = changes_model(id, outputs)

    def react(self, events):
        completion = self.llm.generate(
            BASE_SYSTEM_PROMPT,
            self._prompt(events),
            self.response_model,
        )
        return Reaction(completion.value.changes, completion)

    def _prompt(self, events):
        arriving = "\n".join(
            f"{event.id}: {event.variable} = {event.level}"
            for event in events
        )
        prompt = (
            f"Your component: {self.id}\n"
            f"{self.description}\n\n"
            f"Your local physiological knowledge:\n{self.knowledge}\n\n"
            f"Accepted input variables:\n{', '.join(self.inputs)}\n\n"
            f"Allowed output variables:\n{', '.join(self.outputs)}\n\n"
        )
        return f"{prompt}Incoming events:\n{arriving}"


class Blood:
    uses_llm = False

    def __init__(self, id, outputs, transforms):
        self.id = id
        self.outputs = outputs
        self.transforms = {transform.source: transform for transform in transforms}

    def react(self, events):
        changes = []
        for event in events:
            transform = self.transforms.get(event.variable)
            if transform is None:
                continue
            direction = transform.direction
            level = event.level if direction == "same" else FLIP[event.level]
            changes.append(Change(
                variable=transform.target,
                level=level,
                caused_by=event.id,
            ))
        return Reaction(changes, None)
