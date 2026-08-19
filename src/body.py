import re
from dataclasses import dataclass, field

from src.agent import LeafAgent
from src.schemas import Link

LINK = re.compile(r"^- (\w+) (increases|reduces) (\w+)\.$")


def parse_links(text):
    links = []
    for line in text.splitlines():
        if not line.startswith("- "):
            continue
        match = LINK.match(line)
        if not match:
            raise ValueError(f"malformed knowledge link: {line}")
        links.append(Link(*match.groups()))
    return links


@dataclass
class RouterNode:
    id: str
    description: str
    children: list = field(default_factory=list)


class Body:
    def __init__(self, config, llm, knowledge_dir):
        self.nodes = {}
        self.root = self._build("body", config, llm, knowledge_dir)
        self.links = {leaf.id: parse_links(leaf.knowledge) for leaf in self.leaves}
        self._check_links()

    @property
    def leaves(self):
        return [node for node in self.nodes.values() if isinstance(node, LeafAgent)]

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
            node = LeafAgent(
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

    def _check_links(self):
        registry = set(self.registry)
        for leaf in self.leaves:
            for link in self.links[leaf.id]:
                if link.target not in leaf.variables:
                    raise ValueError(
                        f"'{leaf.id}' states an effect on '{link.target}', which it does not declare"
                    )
                if link.source not in registry:
                    raise ValueError(
                        f"'{leaf.id}' cites '{link.source}', which no component declares"
                    )
