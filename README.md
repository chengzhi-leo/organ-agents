# organ-agents

Physiological agents reconstruct source-grounded causal pathways as canonical event graphs.

The active glucose benchmark uses textbook ground truth under `data/ground_truth/gt_mvp/`. Every graph
is validated against `config/schema_mvp.yaml`; the retired simulator experiment is isolated
under `archive/glucose_simulator/` and is not part of the active evaluation path.

Run a scenario:

```bash
conda run --no-capture-output -n evo python main.py \
  --config config/run.yaml \
  --input data/inputs/gt_mvp/glucose_case_01.json
```

Evaluate a prediction:

```bash
conda run --no-capture-output -n evo python eval.py \
  --pathway outputs/experiments/glucose_mvp/<date>/<time>/pathway.json \
  --truth data/ground_truth/gt_mvp/glucose_case_01.json \
  --schema config/schema_mvp.yaml
```
