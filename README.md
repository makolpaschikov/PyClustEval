# PyClustEval

PyClustEval — desktop-приложение и Python framework для сравнения локальных и федеративных алгоритмов кластеризации.

## Возможности

- локальные алгоритмы: K-Means, DBSCAN, GMM, Agglomerative;
- федеративные NumPy-реализации: K-Means, Fuzzy C-Means, diagonal GMM;
- федеративные Flower Simulation-реализации тех же алгоритмов;
- IID и Dirichlet partitioning;
- ARI, NMI, Silhouette, Davies–Bouldin, Calinski–Harabasz;
- desktop UI на tkinter;
- typed DTO для запросов и отчётов;
- автоматическая история экспериментов в JSON, CSV и log.

## Требования

Рекомендуется Python 3.12.

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[flower,dev]"
```

Для запуска только локальных и NumPy-федеративных алгоритмов:

```powershell
python -m pip install -e ".[dev]"
```

## Запуск UI

```powershell
python pyclusteval_ui.py
```


## Fair benchmark profile and compatibility tests

Comparisons now use one explicit common benchmark profile: the same seed, requested `k`, client count, partition, round budget, convergence tolerance, and compatible local iteration budget are passed to both algorithms. Algorithm-specific parameters (for example HF_DBSCAN `L`, density thresholds, fuzziness, or GMM regularization) remain isolated per algorithm and no longer leak into the competitor. If `K` is left blank in the UI, the benchmark uses the number of ground-truth classes as an explicitly recorded **oracle-k** condition.

The default federated partition guarantees at least 3 samples/client, matching the strictest currently integrated author implementation (NN-FC). Each result stores `model_state["benchmark"]` with its effective parameters and `model_state["diagnostics"]` with noise/degeneracy information.

A compatibility regression matrix covers the four built-in datasets. In the current non-Flower sweep there are 80 cases: **73 normal, 6 degenerate, 1 near-degenerate, 0 execution errors**. Degenerate runs are not silently hyperparameter-tuned; they remain visible as benchmark results. See `docs/BENCHMARK_FAIRNESS.md` and `docs/compatibility_matrix.csv`.

```powershell
python tools/compatibility_matrix.py --output docs/compatibility_matrix.csv
```

## История запусков

Каждый успешный эксперимент создаёт каталог:

```text
history/
└── YYYY-MM-DD_HH-MM-SS/
    ├── report.json
    ├── results.csv
    └── execution.log
```

Если несколько запусков начались в одну секунду, используются суффиксы `_2`, `_3` и далее.

## Архитектура

```text
UI
  -> ComparisonService
      -> DatasetRegistry
      -> Preprocessing
      -> Partitioning
      -> AlgorithmRegistry
      -> Algorithm Adapter
      -> Metrics
      -> HistoryStore
  -> ComparisonReport
```

UI больше не содержит orchestration. Он создаёт `RunRequest`, запускает `ComparisonService` в worker thread и отображает `ComparisonReport`.

Подробное описание и редактируемая Draw.io-схема находятся в `docs/`.

## Структура

```text
PyClustEval/
├── pyclusteval_ui.py
├── clustering_eval/
│   ├── application/
│   │   ├── dto.py
│   │   └── comparison_service.py
│   ├── algorithms/
│   ├── datasets/
│   ├── experiments/
│   ├── flower_adapter/
│   ├── metrics/
│   └── results/
│       ├── history_store.py
│       └── store.py
├── configs/
├── docs/
├── history/
└── tests/
```

## Тесты

```powershell
python -m pytest
```

Flower-тесты требуют установленного `flwr[simulation]` и Ray.

## Author-source adapted algorithms

The federated registry also contains five adapters that execute the specific author implementations supplied with this project:

- `Adapted FKM` — swiergarst/fedKMeans
- `Adapted HF_DBSCAN` — GM862001/F_DBSCAN (horizontal implementation)
- `Adapted FKDC` — mlyizhang/FKDC
- `Adapted NN-FC` — mlyizhang/nnfc
- `Adapted p-FClus` — supplied `p-FClus-main.zip` / arXiv:2407.04302

See `docs/ADAPTATION.md` for exact source commits, executed files, and every adaptation seam.

### Compatibility and density sensitivity audits

```bash
python tools/compatibility_matrix.py --output docs/compatibility_matrix.csv
python tools/density_sensitivity.py --output docs/density_sensitivity.csv
```

The density sweep uses the same five-candidate unlabeled budget and the shared `density_min_samples` threshold for DBSCAN/HF_DBSCAN; ARI/NMI are not used for parameter selection. See `docs/BENCHMARK_FAIRNESS.md`.
