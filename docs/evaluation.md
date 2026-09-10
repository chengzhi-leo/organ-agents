# Offline pathway evaluation

This evaluator is an offline research tool and is never imported or called by the optimization
runtime. The runtime and its agents see only the input and requested final outputs stored together in
one scenario file.

Prediction and textbook reference pathways use the same canonical event graph schema. Offline
evaluation is deterministic and answers three separate questions without feeding any metric or
diagnostic back to Meta or Critic.

```bash
conda run --no-capture-output -n evo python eval.py \
  --pathway outputs/experiments/graph_optimization/<date>/<time>/<scenario_id>/best_pathway.json \
  --truth data/ground_truth/gt_mvp/gt_01_hyperglycemia_insulin.json \
  --schema config/bodies/body.yaml config/bodies/blood.yaml \
  --output outputs/experiments/physiology_mvp/<date>/<time>/<scenario_id>/score.json
```

Ground truth and predictions are validated against the same composed Body and shared Blood schema.
Every response variable must be owned by its emitting component, every input event must be owned by
its component or declared by an external source, and every Blood edge must match its declared source,
target, and direction. Agent inputs are interface metadata rather than graph validity constraints.
Runtime fields and provenance are ignored. Event IDs do not participate in semantic
matching; they connect canonical directional-state nodes for path recovery.

## Primary metrics

### Mechanism precision, recall, and F1

A mechanism is a direct unsigned concept edge:

```python
((source_agent, source_variable), (target_agent, target_variable))
```

This measures whether the system found the direct causal relationships, independently of direction.
Precision penalizes additional mechanisms and recall penalizes missed GT mechanisms.

### Direction accuracy

For every mechanism present in both graphs, evaluation compares the complete set of
`(source_level, target_level)` pairs. A mechanism is directionally correct only when the predicted
and GT sets are identical. Accuracy is calculated over matched mechanisms, so it must always be
reported with mechanism recall. It is undefined when no mechanisms match.

### Complete path recall

GT paths are enumerated from declared inputs to terminal nodes on the event-ID graph, then converted
to signed semantic sequences. A path is recovered only when one continuous prediction path from a
declared input matches the full sequence. Converging mechanisms share one canonical target node, so
each incoming edge can participate in a continuous path through that node.

```text
complete path recall = recovered GT paths / all GT paths
```

Extra mechanisms do not change path recall; mechanism precision reports them separately.

## Diagnostics

The evaluator lists missed mechanisms, spurious mechanisms, wrong-direction mechanisms, and broken
GT paths. Node F1, signed edge F1, and GT edge coverage are not reported because they either conflate
the three questions or duplicate another quantity.

## Study-level reporting

Report every metric per case. Across a benchmark, use the macro mean across cases so larger graphs do
not dominate. For a manuscript, pre-specify the three primary metrics and report uncertainty across
cases, including confidence intervals and the underlying numerator and denominator counts.
