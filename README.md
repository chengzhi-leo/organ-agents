# organ-agents

organ-agents builds compact, executable causal graphs from collaborating physiological agents. For
each scenario, the system knows only an initial perturbation and the desired terminal output states.
It iteratively changes the agent topology until the predicted output is correct and the graph is as
simple as possible.

## Pipeline

The Meta Agent selects at most the configured number of agents and creates an initial directed
execution graph. A graph edge is the complete communication contract: after agent A emits a local
change and Blood translates its representation, the event can reach agent B only when `A -> B`
exists. There is no Router.

A forward run produces an event-level causal pathway and terminal outputs. The Critic compares those
outputs with the target, judges the graph's `nodes + edges` complexity, and decides whether a mutated
candidate is better than the incumbent. The Meta Agent then proposes one to three graph operations.
`main.py` repeats this loop while retaining only Critic-approved improvements.

The runtime never loads the reference causal graph. Each file under `data/scenarios/` contains one
scenario ID, one initial perturbation, and the requested final output states.

## Run

Use the `evo` conda environment:

```bash
conda run --no-capture-output -n evo python main.py \
  --config config/run.yaml \
  --scenario data/scenarios/gt_mvp/glucose_case_01.json
```

The scenario file is the only experiment input passed to `main.py`; its input and output share one
`scenario_id` by construction. Each run saves the best execution graph, its predicted pathway, the
complete optimization history, per-iteration artifacts, usage totals, and an HTML report under the
configured output directory.

```json
{
  "scenario_id": "glucose_case_01",
  "input": {
    "agent_id": "blood",
    "variable": "blood_glucose",
    "level": "increased"
  },
  "output": [
    {
      "agent_id": "blood",
      "variable": "blood_glucose",
      "level": "decreased"
    }
  ]
}
```

## Core contracts

- `config/bodies/body.yaml`: fixed local-agent registry and interfaces
- `config/bodies/blood.yaml`: deterministic shared Blood transformations
- `config/run.yaml`: model, forward, optimization, and output budgets
- `src/schemas.py`: strict runtime schemas
- `docs/architecture.md`: execution and optimization semantics

The result is named `best_found`: it is the best graph discovered within the configured mutation and
patience budget, not a proof of global optimality.
