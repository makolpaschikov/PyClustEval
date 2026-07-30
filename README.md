# clustering-flower-eval

TimeEval-like benchmark framework for comparing clustering algorithms. The core is independent from Flower; Flower is treated as an execution backend/adapter.

## Install

```bash
pip install -e .
```

Optional Flower runtime:

```bash
pip install -e '.[flower]'
```

## Run example

```bash
clustereval run configs/example.yaml
```

Results are written to `results/`.

## Architecture

- `datasets`: dataset registry and federated partitioning
- `algorithms`: unified algorithm adapters
- `experiments`: config parsing, planning, runner
- `metrics`: clustering quality metrics
- `results`: CSV/JSON storage
- `flower_adapter`: placeholder for real Flower ServerApp/ClientApp/Strategy integration
