from src.agent import Agent, BloodTranslator


class Body:
    def __init__(self, schema, llm, knowledge_dir, agent_ids):
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError("Body agent IDs must be unique")
        unknown = set(agent_ids) - set(schema.agents)
        if unknown:
            raise ValueError(f"Body references unknown agents: {sorted(unknown)}")
        selected = set(agent_ids)
        self.schema = schema
        self.agents = [
            Agent(
                agent_id,
                interface.description,
                (knowledge_dir / interface.knowledge).read_text(),
                list(interface.owned_variables),
                llm,
            )
            for agent_id, interface in schema.agents.items()
            if agent_id in selected
        ]
        self.translator = BloodTranslator(
            list(schema.blood.owned_variables),
            schema.blood.transforms,
        )
