# Architecture

## Contracts and information boundary

`config/bodies/body.yaml` is the fixed local-agent registry. Each agent declares its description,
knowledge file, inputs, and owned variables. `config/bodies/blood.yaml` defines deterministic
representation transforms. Blood is shared infrastructure and is never a selectable graph node.

A `Scenario` file contains one scenario ID, one initial directional perturbation, and one or more
requested terminal output states. `main.py` accepts exactly one scenario file per invocation and
never loads a ground-truth causal graph. Meta and Critic therefore have access to the initial input
and final outputs, but not the expected intermediate mechanisms.

## Execution graph

The Meta Agent builds an `ExecutionGraph` with local-agent IDs as nodes and unlabelled directed edges.
`INPUT` is a reserved external source. An edge `A -> B` is the only permission for events produced by
A to reach B. `INPUT` and Blood do not count as nodes. Complexity is exactly:

```text
number of selected local-agent nodes + number of execution edges
```

Every selected node must be reachable from `INPUT`. Duplicate nodes and edges are invalid. The graph
policy is explicit in configuration; the active configuration permits cycles and self-edges so that
feedback and multiple local causal steps remain representable.

## Forward execution

`src/forward.py` executes one graph. Runtime messages pair an event with `source_node_id`. The initial
perturbation uses `INPUT`; an event emitted by A retains A as its propagation source even after Blood
changes its event representation.

Blood transformations run deterministically until no further transform applies. Every intermediate
translation remains in the event pathway, while only the final representation is dispatched through
the producer's outgoing execution edges. Blood transform cycles are rejected during schema loading.

Local agents receive all events dispatched to them in a round and emit only owned changes with one
immediate cause. Different agents may react concurrently. A signed event is expanded once per
propagation source, allowing the same translated state to follow distinct graph routes without
unbounded repetition. Homeostatic closure, no successors, the round limit, and the per-forward
LLM-call limit terminate execution.

Prediction outputs are taken from terminal response occurrences in the raw ledger, then deduplicated
by `(agent_id, variable, level)`. The ledger is separately canonicalized into `PathwayGraph`:
response occurrences with the same signed state are merged, duplicate/self causal edges are removed,
and the initial input remains separate. Canonical merging therefore cannot change output terminality.

## Closed-loop optimization

`main.py` owns the loop and `src/optimize.py` owns the two optimization roles and graph operations.
The initial Meta call sees the registry interfaces, input, requested outputs, graph policy, and agent
limit, then returns a complete graph. It does not receive Blood transforms.

The initial graph runs once and becomes the unconditional initial best. Its first Critic call assesses
output agreement and supplies the first mutation recommendation; it does not make an acceptance
decision. On later rounds, the Critic receives the input, requested outputs, candidate and historical
best graphs, their predictions, controller-computed complexities, and compact traces. It compares
prediction quality first, using lower complexity only when quality is equal, and returns the sole
`accept_candidate` decision. It does not recount or return node and edge totals. No programmatic
prediction score or missing/extra-output diagnostic is computed.

Every later Meta call sees only the current best graph, the Critic recommendation, registry interfaces,
and graph constraints. It proposes a small transactional sequence of `ADD_AGENT`, `REMOVE_AGENT`,
`ADD_EDGE`, `REMOVE_EDGE`, `REPLACE_AGENT`, or `REVERSE_EDGE` operations. Invalid transactions are
rejected without changing the incumbent. A valid candidate is accepted only when the Critic prefers
it. The Critic's `next_recommendation` always targets the graph retained for the next round: the
candidate after acceptance or the historical best after rejection. Acceptance resets patience;
rejection or an invalid mutation increments it. Search stops at the configured mutation limit or
patience limit and returns `best_found`.

## Artifacts

Each scenario directory contains:

- `best_execution_graph.json`
- `best_pathway.json`
- `best_trace.json`
- `optimization.json`
- `run_config.yaml`
- `report.html`
- `iterations/<iteration>/` with graph, forward, Meta, Critic, trace, and decision artifacts

Usage is aggregated across initial Meta, mutation Meta, Critic, and local-agent calls. Rejected
candidates remain fully inspectable.
