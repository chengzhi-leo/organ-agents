from src.body import RouterNode
from src.schemas import Dispatch

MODES = ("index", "llm", "hybrid")

SYSTEM_PROMPT = """
You are the dispatcher in a multi-agent physiological simulation.

You will receive a numbered list of physiological changes. For each change, identify every component in which at least one internal variable may change directly in response to that change.

Route only one causal step. Do not include a component if it would be affected only after another component responds first. Do not include a component merely because it owns the changed variable. Include it when the change drives another of its internal variables: heart_rate increased routes to heart, because heart_rate drives cardiac output inside the heart.

Use the component descriptions below as the authoritative definition of physiological dependencies. Do not invent additional effects, predict downstream propagation, or modify the input changes.

For example:

blood_volume decreased → heart, because the heart responds directly to circulating blood volume. Do not also route it to components that may respond later to changes in cardiac output or arterial pressure.
cardiac_output decreased → vasculature, because the vasculature responds directly to cardiac output.
arterial_pressure decreased → kidney, sympathetic, and adh, because each responds directly to arterial pressure. Do not route it to vasculature merely because arterial pressure is one of its internal variables.

Every input change must appear exactly once in the output, identified in "change" by its number in that list. Also copy its variable and level exactly. An empty agent_ids list is valid when no component responds directly.

Return JSON only:

{
  "assignments": [
    {
      "change": 1,
      "variable": "string",
      "level": "decreased" | "increased",
      "agent_ids": ["component_name"]
    }
  ]
}

Only component names listed below may appear in agent_ids. Names in brackets are system labels for context only and must never be returned.

Components:

"""


class Router:
    def __init__(self, llm, body, mode, retries):
        if mode not in MODES:
            raise ValueError(f"unknown routing mode '{mode}'; expected one of {MODES}")
        self.llm = llm
        self.body = body
        self.mode = mode
        self.retries = retries
        self.cache = {}
        self.audit = []
        self.failures = []
        self.system_prompt = SYSTEM_PROMPT + "\n".join(self._render(body.root, 0))

    def route(self, events):
        pending = sorted({event.key for event in events} - self.cache.keys())
        if pending:
            self._resolve(pending)
        return {event.key: self.cache[event.key] for event in events}

    def _resolve(self, pending):
        derived = {key: self.body.responders(key[0]) for key in pending}
        if self.mode == "index":
            self.cache.update(derived)
            return

        for key, leaves in self._ask(pending).items():
            proposed = [leaf for leaf in leaves if leaf not in derived[key]]
            missed = [leaf for leaf in derived[key] if leaf not in leaves]
            self.audit += self._entries(key, proposed, "proposed") + self._entries(key, missed, "missed")
            self.cache[key] = leaves if self.mode == "llm" else derived[key] + proposed

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
        assignments = completion.value.assignments
        leaves = {leaf.id: leaf for leaf in self.body.leaves}

        answered = sorted(item.change for item in assignments)
        if answered != list(range(1, len(pending) + 1)):
            raise ValueError(f"router answered changes {answered}, expected exactly 1..{len(pending)}")
        unknown = sorted({id for item in assignments for id in item.agent_ids} - leaves.keys())
        if unknown:
            raise ValueError(f"router returned unknown agent ids {unknown}")

        for item in assignments:
            key = pending[item.change - 1]
            if (item.variable, item.level) != key:
                self.audit.append({
                    "variable": key[0],
                    "level": key[1],
                    "agent": f"restated as {item.variable} = {item.level}",
                    "status": "mislabelled",
                })
        return {
            pending[item.change - 1]: [leaves[id] for id in item.agent_ids] for item in assignments
        }

    @staticmethod
    def _entries(key, leaves, status):
        return [
            {"variable": key[0], "level": key[1], "agent": leaf.id, "status": status}
            for leaf in leaves
        ]

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
