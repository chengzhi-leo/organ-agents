import json

from src.schemas import (
    INPUT_NODE,
    CandidateCritique,
    ExecutionEdge,
    ExecutionGraph,
    ExecutionGraphDraft,
    InitialCritique,
    MutationPlan,
)

INITIAL_META_PROMPT = """
You design a compact directed execution graph for a physiological multi-agent system.

The graph must connect the given input to the requested final outputs through local agents from the registry. Each edge A -> B means that every event emitted by A, after deterministic Blood translation, may be delivered directly to B. INPUT is the only external graph source. Blood is shared deterministic infrastructure and is not a selectable node.

Choose only agents needed for a plausible complete causal response. Preserve necessary relays and parallel branches while avoiding speculative agents and edges. Every selected node must be reachable from INPUT. Do not duplicate nodes or edges. Follow the supplied cycle and self-edge policies.

Return JSON only:

{
  "nodes": ["agent_id"],
  "edges": [{"source": "INPUT|agent_id", "target": "agent_id"}]
}
"""

MUTATION_META_PROMPT = """
You improve an existing physiological agent execution graph using a small transactional mutation.

The current graph is the best graph accepted so far. Follow the Critic recommendation and propose between the configured minimum and maximum number of operations. Do not redesign the entire graph. Every operation must be necessary and must use only agents from the registry.

Available operations:
- ADD_AGENT with agent_id
- REMOVE_AGENT with agent_id
- ADD_EDGE with source and target
- REMOVE_EDGE with source and target
- REPLACE_AGENT with agent_id and replacement_agent_id
- REVERSE_EDGE with source and target

ADD_AGENT only adds a node, so add a connecting edge in the same transaction when needed. REMOVE_AGENT also removes incident edges. REPLACE_AGENT preserves incident topology under the new ID. INPUT edges cannot be reversed. Do not return a no-op.

Return JSON only:

{
  "operations": [
    {"type": "ADD_AGENT", "agent_id": "agent_id"},
    {"type": "ADD_EDGE", "source": "INPUT", "target": "agent_id"}
  ]
}
"""

CRITIC_BASE_PROMPT = """
You critique a physiological agent execution graph.

You may use only the supplied scenario input, requested final outputs, predicted final outputs, execution graph, and forward trace. You do not know and must not infer that a ground-truth causal graph exists.

Judge semantically whether the prediction agrees with the requested final outputs. The controller supplies exact node, edge, and total complexity measurements. Use them to identify unnecessary structure and causal omissions from the runtime trace. Do not recalculate or return these measurements. Do not output deterministic scores, missing-output lists, extra-output lists, or a replacement graph.
"""

INITIAL_CRITIC_PROMPT = f"""{CRITIC_BASE_PROMPT}
The supplied graph is the unconditional initial best. Analyze it and recommend one focused change for the next iteration. There is no acceptance decision.

Return JSON only:

{{
  "prediction_matches_output": true,
  "analysis": "semantic assessment",
  "next_recommendation": "small next-step advice"
}}
"""

COMPARISON_CRITIC_PROMPT = f"""{CRITIC_BASE_PROMPT}
Compare the current candidate with the historical best. Compare prediction quality first. Accept the candidate only when it is more consistent with the requested outputs, or when prediction quality is equally good and the candidate graph is simpler. Never trade worse prediction quality for lower complexity.

prediction_matches_output describes the current candidate, not the historical best.
next_recommendation must target the graph used in the next iteration. If you accept the candidate, recommend how to improve the candidate. If you reject it, recommend how to improve the historical best.

Return JSON only:

{{
  "prediction_matches_output": true,
  "accept_candidate": true,
  "analysis": "semantic assessment",
  "next_recommendation": "small next-step advice",
  "decision_reason": "accept or reject rationale"
}}
"""


class GraphOptimizer:
    def __init__(self, schema, llm, config):
        self.llm = llm
        self.agent_ids = list(schema.agents)
        self.max_agents = config["max_agents"]
        self.min_operations = config["min_operations_per_mutation"]
        self.max_operations = config["max_operations_per_mutation"]
        self.allow_cycles = config["allow_cycles"]
        self.allow_self_edges = config["allow_self_edges"]
        if self.max_agents <= 0:
            raise ValueError("optimization.max_agents must be positive")
        if not 0 < self.min_operations <= self.max_operations:
            raise ValueError("optimization mutation operation bounds are invalid")
        graph_policies = self.allow_cycles, self.allow_self_edges
        if not all(isinstance(policy, bool) for policy in graph_policies):
            raise ValueError("optimization graph policies must be booleans")
        self.catalog = [
            {
                "agent_id": agent_id,
                "description": interface.description,
                "inputs": interface.inputs,
                "owned_variables": interface.owned_variables,
            }
            for agent_id, interface in schema.agents.items()
        ]

    def initialize(self, scenario):
        prompt = json.dumps({
            "scenario_input": scenario.input.model_dump(),
            "requested_output": [output.model_dump() for output in scenario.output],
            "max_agents": self.max_agents,
            "graph_policy": {
                "allow_cycles": self.allow_cycles,
                "allow_self_edges": self.allow_self_edges,
            },
            "agent_registry": self.catalog,
        }, indent=2)
        completion = self.llm.generate(INITIAL_META_PROMPT, prompt, ExecutionGraphDraft)
        draft = completion.value
        graph = ExecutionGraph(
            scenario_id=scenario.scenario_id,
            nodes=draft.nodes,
            edges=draft.edges,
        )
        return self.validate(graph), completion

    def propose_mutation(self, graph, recommendation):
        prompt = json.dumps({
            "current_graph": graph.model_dump(),
            "critic_recommendation": recommendation,
            "operation_bounds": {
                "minimum": self.min_operations,
                "maximum": self.max_operations,
            },
            "graph_policy": {
                "allow_cycles": self.allow_cycles,
                "allow_self_edges": self.allow_self_edges,
            },
            "agent_registry": self.catalog,
        }, indent=2)
        completion = self.llm.generate(MUTATION_META_PROMPT, prompt, MutationPlan)
        operations = completion.value.operations
        if not self.min_operations <= len(operations) <= self.max_operations:
            raise ValueError(
                f"Meta Agent returned {len(operations)} operations; expected "
                f"{self.min_operations}..{self.max_operations}"
            )
        return operations, completion

    def critique_initial(self, scenario, graph, result):
        prompt = json.dumps({
            "scenario_input": scenario.input.model_dump(),
            "requested_output": [output.model_dump() for output in scenario.output],
            "initial_best": {
                "graph": graph.model_dump(),
                "complexity": graph_complexity(graph),
                "prediction": result.critic_dump(),
            },
        }, indent=2)
        return self.llm.generate(INITIAL_CRITIC_PROMPT, prompt, InitialCritique)

    def compare(self, scenario, best_graph, best_result, candidate_graph, candidate_result):
        prompt = json.dumps({
            "scenario_input": scenario.input.model_dump(),
            "requested_output": [output.model_dump() for output in scenario.output],
            "historical_best": {
                "graph": best_graph.model_dump(),
                "complexity": graph_complexity(best_graph),
                "prediction": best_result.critic_dump(),
            },
            "current_candidate": {
                "graph": candidate_graph.model_dump(),
                "complexity": graph_complexity(candidate_graph),
                "prediction": candidate_result.critic_dump(),
            },
        }, indent=2)
        return self.llm.generate(
            COMPARISON_CRITIC_PROMPT,
            prompt,
            CandidateCritique,
        )

    def apply(self, graph, operations):
        nodes = list(graph.nodes)
        edges = [(edge.source, edge.target) for edge in graph.edges]
        for operation in operations:
            if operation.type == "ADD_AGENT":
                if operation.agent_id in nodes:
                    raise ValueError(f"ADD_AGENT is a no-op for '{operation.agent_id}'")
                nodes.append(operation.agent_id)
            elif operation.type == "REMOVE_AGENT":
                if operation.agent_id not in nodes:
                    raise ValueError(f"REMOVE_AGENT references absent '{operation.agent_id}'")
                nodes.remove(operation.agent_id)
                edges = [
                    edge for edge in edges if operation.agent_id not in edge
                ]
            elif operation.type == "ADD_EDGE":
                edge = operation.source, operation.target
                if edge in edges:
                    raise ValueError(f"ADD_EDGE is a no-op for {edge}")
                edges.append(edge)
            elif operation.type == "REMOVE_EDGE":
                edge = operation.source, operation.target
                if edge not in edges:
                    raise ValueError(f"REMOVE_EDGE references absent {edge}")
                edges.remove(edge)
            elif operation.type == "REPLACE_AGENT":
                old = operation.agent_id
                new = operation.replacement_agent_id
                if old not in nodes:
                    raise ValueError(f"REPLACE_AGENT references absent '{old}'")
                if new in nodes or new == old:
                    raise ValueError(f"REPLACE_AGENT cannot use '{new}'")
                nodes[nodes.index(old)] = new
                edges = [
                    (new if source == old else source, new if target == old else target)
                    for source, target in edges
                ]
            elif operation.type == "REVERSE_EDGE":
                edge = operation.source, operation.target
                if edge not in edges:
                    raise ValueError(f"REVERSE_EDGE references absent {edge}")
                if operation.source == INPUT_NODE or operation.source == operation.target:
                    raise ValueError(f"REVERSE_EDGE cannot reverse {edge}")
                reverse = operation.target, operation.source
                if reverse in edges:
                    raise ValueError(f"REVERSE_EDGE would duplicate {reverse}")
                edges[edges.index(edge)] = reverse

        candidate = ExecutionGraph(
            scenario_id=graph.scenario_id,
            nodes=nodes,
            edges=[ExecutionEdge(source=source, target=target) for source, target in edges],
        )
        if candidate == graph:
            raise ValueError("mutation must change the execution graph")
        return self.validate(candidate)

    def validate(self, graph):
        return graph.validate_for(
            self.agent_ids,
            self.max_agents,
            self.allow_cycles,
            self.allow_self_edges,
        )


def operation_dump(operations):
    return [operation.model_dump(exclude_none=True) for operation in operations]


def graph_complexity(graph):
    return {
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "total": graph.complexity,
    }
