class RuleBasedRouter:
    """Routes events by schema-declared inputs.

    A future LLMRouter should implement the same route interface. Runtime configuration must select
    exactly one router strategy.
    """

    def __init__(self, body):
        self.agents = body.leaves
        self.schema = body.schema

    def route(self, events):
        return {
            event.key: [
                agent
                for agent in self.agents
                if event.variable in self.schema.interface(agent.id).inputs
            ]
            for event in events
        }


def build(body, config):
    mode = config["mode"]
    if mode == "rule_based":
        return RuleBasedRouter(body)
    if mode == "llm":
        raise NotImplementedError("LLM router is not implemented")
    raise ValueError(f"unknown router mode '{mode}'")
