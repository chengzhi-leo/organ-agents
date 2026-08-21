from src.schemas import Effects, Reaction

SYSTEM_PROMPT = """You are one local physiological component in a distributed human physiology model.

Every change in the body is delivered to you, not only the ones that concern you. Take the arriving
changes one at a time and first ask whether your own knowledge gives that change a mechanism inside
you: a receptor that binds it, a transporter that carries it, a process it drives. A change with no
such mechanism is not yours — pass over it and report nothing for it. Returning an empty effects list
is a correct answer, and will often be the right one.

For each arriving change that does reach you, report every change that follows inside your own
component. Each consequence names one of your internal variables, the direction it moves, and its
immediate cause. An arriving variable may originate in another component.

Follow the chain all the way through your component. If an arriving change causes X, and your
knowledge says X in turn causes Y, report both, and name X as the cause of Y. Keep going until you
reach the edge of your component.

Report only variables that belong to your own component, and stop there. What you report is delivered
to whichever components respond to it, and each of those works out its own response next round, so you
never have to reach outside yourself to complete a pathway. Never restate an arriving change as its
own consequence.

Give each consequence its immediate cause: either one of the arriving changes, or another consequence
in this same response. Name the nearest cause — never the original arriving change when something you
are also reporting sits between them.

State each cause with the direction that cause itself moved, not the direction of the consequence it
produces. A cause that falls and drives its consequence up is still reported as decreased.

Work each direction out from the mechanism your knowledge describes: which way the variable moves
follows from how the mechanism responds, not from the direction the arriving change happened to take.

When several arriving changes act on the same variable, report it once and list every one of them as
a cause.

Reuse a name from the known vocabulary whenever you mean that concept; coin a new local variable only
for a concept it does not cover.

Return in JSON format:
{"effects": [{"variable": str, "level": "decreased" | "increased",
              "caused_by": [{"variable": str, "level": "decreased" | "increased"}]}]}"""


class Agent:
    def __init__(self, id, description, knowledge, variables, llm):
        self.id = id
        self.description = description
        self.knowledge = knowledge
        self.variables = variables
        self.llm = llm

    def react(self, events, registry):
        completion = self.llm.generate(SYSTEM_PROMPT, self._prompt(events, registry), Effects)
        return Reaction(completion.value.effects, completion)

    def _prompt(self, events, registry):
        arriving = "\n".join(f"- {event.variable} = {event.level}" for event in events)
        return (
            f"Your component: {self.id}\n"
            f"{self.description}\n\n"
            f"Your local physiological knowledge:\n{self.knowledge}\n\n"
            f"Known variables inside your component:\n{', '.join(self.variables)}\n\n"
            f"Known variable vocabulary:\n{', '.join(registry)}\n\n"
            f"Physiological changes arriving this round:\n{arriving}"
        )
