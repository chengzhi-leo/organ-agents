from dataclasses import dataclass, field

from src.agent import Agent, Blood


@dataclass
class RouterNode:
    id: str
    children: list = field(default_factory=list)


class Body:
    def __init__(self, config, schema, llm, knowledge_dir):
        self.nodes = {}
        self.schema = schema
        self._build("body", config, llm, knowledge_dir)

    @property
    def leaves(self):
        return [node for node in self.nodes.values() if not isinstance(node, RouterNode)]

    def _build(self, node_id, config, llm, knowledge_dir):
        if node_id in self.nodes:
            raise ValueError(f"node '{node_id}' appears more than once in the hierarchy")
        if node_id == "blood":
            interface = self.schema.blood
            node = Blood(
                node_id,
                list(interface.outputs),
                interface.transforms,
            )
            self.nodes[node_id] = node
            return node
        if node_id not in config:
            raise ValueError(f"node '{node_id}' is referenced as a child but not defined")

        spec = config[node_id]
        if spec.get("type") == "router":
            node = RouterNode(node_id)
        else:
            if node_id not in self.schema.agents:
                raise ValueError(f"node '{node_id}' is missing from the schema")
            interface = self.schema.agents[node_id]
            inputs = list(interface.inputs)
            outputs = list(interface.outputs)
            node = Agent(
                node_id,
                spec["description"],
                (knowledge_dir / spec["knowledge"]).read_text(),
                inputs,
                outputs,
                llm,
            )

        self.nodes[node_id] = node
        if isinstance(node, RouterNode):
            node.children = [
                self._build(child_id, config, llm, knowledge_dir)
                for child_id in spec["children"]
            ]
        return node
