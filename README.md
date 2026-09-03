# organ-agents

Physiological agents reconstruct source-grounded causal pathways as canonical event graphs.

The active glucose benchmark uses textbook ground truth under `data/ground_truth/glucose/`. Every graph
is validated against `config/vocabularies/glucose.yaml`; the retired simulator experiment is isolated
under `archive/glucose_simulator/` and is not part of the active evaluation path.

Run a scenario:

```bash
conda run --no-capture-output -n evo python main.py \
  --config config/run.yaml \
  --ground-truth data/ground_truth/glucose/gt01_high_glucose_insulin_response.json
```

Evaluate a prediction:

```bash
conda run --no-capture-output -n evo python eval.py \
  --pathway outputs/logs/<date>/<time>/pathway.json \
  --truth data/ground_truth/glucose/gt01_high_glucose_insulin_response.json \
  --vocabulary config/vocabularies/glucose.yaml \
  --prediction-vocabulary constrained
```
