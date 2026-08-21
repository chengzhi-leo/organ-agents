from dataclasses import dataclass, field

from src.agent import Agent


@dataclass
class RouterNode:
    id: str
    description: str
    children: list = field(default_factory=list)


class Body:
    def __init__(self, config, llm, knowledge_dir):
        self.nodes = {}
        self.root = self._build("body", config, llm, knowledge_dir)

    @property
    def leaves(self):
        return [node for node in self.nodes.values() if isinstance(node, Agent)]

    @property
    def registry(self):
        return sorted({variable for leaf in self.leaves for variable in leaf.variables})

    def _build(self, node_id, config, llm, knowledge_dir):
        if node_id in self.nodes:
            raise ValueError(f"node '{node_id}' appears more than once in the hierarchy")
        if node_id not in config:
            raise ValueError(f"node '{node_id}' is referenced as a child but not defined")

        spec = config[node_id]

        if spec["type"] == "router":
            node = RouterNode(node_id, spec["description"])
        elif spec["type"] == "leaf":
            node = Agent(
                node_id,
                spec["description"],
                (knowledge_dir / spec["knowledge"]).read_text(),
                list(spec["variables"]),
                llm,
            )
        else:
            raise ValueError(f"node '{node_id}' has unknown type '{spec['type']}'")

        self.nodes[node_id] = node
        if isinstance(node, RouterNode):
            node.children = [
                self._build(child_id, config, llm, knowledge_dir)
                for child_id in spec["children"]
            ]
        return node
