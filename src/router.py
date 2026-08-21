from src.body import RouterNode
from src.schemas import Dispatch

SYSTEM_PROMPT = """
You are the router in a multi-agent physiological simulation.

For each physiological change, select the agents that should receive it.

Route a change to an agent if the change is relevant to that agent's
physiological function or variables. A change may be routed to multiple agents.

Do not predict the agent's response or generate new physiological changes.
The receiving agent will decide whether and how its own state changes.

Return every input change exactly once. Copy its variable and level exactly.
If no agent is relevant, return an empty agent_ids list.

Return JSON only:

{
  "assignments": [
    {
      "change": "index of the change",
      "variable": "string",
      "level": "decreased" | "increased",
      "agent_ids": ["component_name"]
    }
  ]
}

Only component names listed below may appear in agent_ids. Names in brackets are system labels for context only and must never be returned.

Components:

"""


class Broadcast:
    def __init__(self, body):
        self.leaves = body.leaves
        self.audit = []
        self.failures = []

    def route(self, events):
        return {event.key: self.leaves for event in events}


class LLMRouter:
    def __init__(self, llm, body, retries):
        self.llm = llm
        self.body = body
        self.retries = retries
        self.leaves = {leaf.id: leaf for leaf in body.leaves}
        self.cache = {}
        self.audit = []
        self.failures = []
        self.system_prompt = SYSTEM_PROMPT + "\n".join(self._render(body.root, 0))

    def route(self, events):
        pending = sorted({event.key for event in events} - self.cache.keys())
        if pending:
            self.cache.update(self._ask(pending))
        return {event.key: self.cache[event.key] for event in events}

    def _ask(self, pending):
        for attempt in range(self.retries + 1):
            try:
                return self._request(pending)
            except ValueError as error:
                self.failures.append(str(error))
                if attempt == self.retries:
                    raise

    def _request(self, pending):
        changes = "\n".join(
            f"{number}. {variable} = {level}"
            for number, (variable, level) in enumerate(pending, 1)
        )
        prompt = f"Physiological changes to route:\n{changes}"
        completion = self.llm.generate(self.system_prompt, prompt, Dispatch)
        answers = [(self._number(item.change), item) for item in completion.value.assignments]

        answered = sorted(number for number, _ in answers)
        if answered != list(range(1, len(pending) + 1)):
            raise ValueError(f"router answered changes {answered}, expected exactly 1..{len(pending)}")
        unknown = sorted({id for _, item in answers for id in item.agent_ids} - self.leaves.keys())
        if unknown:
            raise ValueError(f"router returned unknown agent ids {unknown}")

        for number, item in answers:
            key = pending[number - 1]
            if (item.variable, item.level) != key:
                self.audit.append({
                    "variable": key[0],
                    "level": key[1],
                    "agent": f"restated as {item.variable} = {item.level}",
                    "status": "mislabelled",
                })
        return {
            pending[number - 1]: [self.leaves[id] for id in item.agent_ids]
            for number, item in answers
        }

    @staticmethod
    def _number(change):
        if not change.strip().isdigit():
            raise ValueError(f"router returned '{change}', which is not a change number")
        return int(change.strip())

    def _render(self, node, depth):
        indent = "  " * depth
        if isinstance(node, RouterNode):
            return [f"{indent}[{node.id}] — {node.description}", ""] + [
                line for child in node.children for line in self._render(child, depth + 1)
            ]
        return [
            f"{indent}{node.id}",
            f"{indent}  {node.description}",
            f"{indent}  internal variables: {', '.join(node.variables)}",
            "",
        ]


def build(config, llm, body):
    if config["mode"] == "broadcast":
        return Broadcast(body)
    if config["mode"] == "llm":
        return LLMRouter(llm, body, config["retries"])
    raise ValueError(
        f"routing declares unknown mode '{config['mode']}'; expected 'broadcast' or 'llm'"
    )
