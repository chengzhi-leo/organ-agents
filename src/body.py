from dataclasses import dataclass, field

from src.agent import Agent, Blood


@dataclass
class RouterNode:
    id: str
    description: str
    children: list = field(default_factory=list)


class Body:
    def __init__(self, config, vocabulary, llm, knowledge_dir, vocabulary_mode):
        self.nodes = {}
        self.vocabulary = vocabulary
        self.vocabulary_mode = vocabulary_mode
        self.root = self._build("body", config, llm, knowledge_dir)
        self._validate_transfers(config)

    @property
    def leaves(self):
        return [node for node in self.nodes.values() if not isinstance(node, RouterNode)]

    def _build(self, node_id, config, llm, knowledge_dir):
        if node_id in self.nodes:
            raise ValueError(f"node '{node_id}' appears more than once in the hierarchy")
        if node_id not in config:
            raise ValueError(f"node '{node_id}' is referenced as a child but not defined")

        spec = config[node_id]
        if spec.get("type") == "router":
            node = RouterNode(node_id, spec["description"])
        else:
            if node_id not in self.vocabulary.agents:
                raise ValueError(f"node '{node_id}' is missing from the vocabulary")
            vocabulary = self.vocabulary.agents[node_id]
            variables = list(vocabulary.variables)
            if vocabulary.kind == "llm_agent":
                node = Agent(
                    node_id,
                    spec["description"],
                    (knowledge_dir / spec["knowledge"]).read_text(),
                    variables,
                    llm,
                    self.vocabulary_mode,
                )
            elif vocabulary.kind == "translator_environment":
                node = Blood(node_id, spec["description"], variables, spec["transfers"])
            else:
                raise ValueError(
                    f"node '{node_id}' has unsupported runtime kind '{vocabulary.kind}'"
                )

        self.nodes[node_id] = node
        if isinstance(node, RouterNode):
            node.children = [
                self._build(child_id, config, llm, knowledge_dir)
                for child_id in spec["children"]
            ]
        return node

    def _validate_transfers(self, config):
        for node in self.leaves:
            if not isinstance(node, Blood):
                continue
            for transfer in config[node.id]["transfers"]:
                self._validate_endpoint(transfer["source"])
                self._validate_endpoint(transfer["target"])
                if transfer["target"]["agent_id"] != node.id:
                    raise ValueError(f"blood transfer target must belong to '{node.id}'")

    def _validate_endpoint(self, endpoint):
        self.vocabulary.validate_owner(
            endpoint["agent_id"], endpoint["variable"], "transfer endpoint"
        )
