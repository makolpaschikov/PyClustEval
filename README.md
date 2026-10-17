# PyClustEval

PyClustEval — desktop-приложение и Python framework для сравнения локальных и федеративных алгоритмов кластеризации.

## Возможности

- локальные алгоритмы: K-Means, DBSCAN, GMM, Agglomerative;
- федеративные NumPy-реализации: K-Means, Fuzzy C-Means, diagonal GMM;
- федеративные Flower Simulation-реализации тех же алгоритмов;
- IID, Dirichlet, Quantity skew и Label-limited partitioning;
- Partial Participation и client dropout с общим deterministic schedule;
- `Privacy: None / Gaussian DP` для record-level input perturbation;
- ARI, NMI, Silhouette, Davies–Bouldin, Calinski–Harabasz;
- встроенные Iris, Wine, Digits, Blobs + UCI Dry Bean (13 611 × 16, 7 классов) + MNIST (`mnist_10k` и `mnist_full`);
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


## UCI Dry Bean

В селектор датасетов добавлен `dry_bean` — официальный **Dry Bean Dataset** из UCI Machine Learning Repository (13 611 объектов, 16 числовых признаков, 7 классов; UCI id 602, DOI `10.24432/C50S4B`, CC BY 4.0).

При первом выборе `dry_bean` PyClustEval скачивает официальный UCI ZIP (~4.5 MB), извлекает `Dry_Bean_Dataset.arff` и кэширует его в `~/.cache/pyclusteval/datasets/dry_bean/`. Повторные запуски работают из кэша. Папку кэша можно переопределить переменной окружения `PYCLUSTEVAL_DATA_DIR`.

Важно: Dry Bean существенно крупнее Iris/Wine. `Adapted NN-FC`, `Adapted FKDC` и другие авторские реализации с квадратичными/дорогими внутренними операциями могут работать на полном наборе заметно дольше. Это не причина автоматически урезать датасет: UI по умолчанию использует все 13 611 объектов.

При `Gaussian DP` текущий механизм по-прежнему клипует **raw X**. У Dry Bean признаки имеют сильно разные масштабы, поэтому `DP clip norm=1.0` является очень жёстким значением; для DP-экспериментов его нужно выбирать осознанно и фиксировать в протоколе, а не сравнивать с другими датасетами без учёта масштаба.

## MNIST

В селектор добавлены два прозрачных режима одного и того же канонического MNIST:

- `mnist_10k` — рекомендуемый benchmark-профиль: детерминированная stratified-выборка 10 000 объектов из полного корпуса 70 000, seed=42;
- `mnist_full` — полный MNIST: 70 000 объектов, 784 признака (28×28), 10 классов, без автоматического subsampling.

При первом использовании четыре стандартных IDX gzip-файла скачиваются лениво и кэшируются в `~/.cache/pyclusteval/datasets/mnist/` (либо в `PYCLUSTEVAL_DATA_DIR/mnist/`). Пиксели преобразуются из uint8 0..255 во float32 [0,1] до algorithm-specific preprocessing.

Для научного отчёта не смешивайте `mnist_10k` и `mnist_full` под одним названием: в истории/Excel они остаются разными dataset names. На 784 измерениях `Adapted HF_DBSCAN`, `FKDC`, `NN-FC` и некоторые другие авторские реализации могут быть очень дорогими; `mnist_full` предназначен прежде всего для алгоритмов, которые действительно масштабируются до 70k×784.

При Gaussian DP `clip_norm=1.0` всё ещё является довольно жёстким ограничением для 784-мерного изображения даже после нормализации пикселей; DP-параметры нужно фиксировать отдельно в протоколе.

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

## Multi-algorithm comparisons

The desktop UI supports selecting any number of algorithms (minimum two) in one experiment.
For federated runs, PyClustEval creates the client partition exactly once before any selected
algorithm starts and reuses the same client sample indices for every algorithm in that experiment.
The shared partition fingerprint is persisted in history/results for reproducibility. Algorithm-specific
preprocessing may transform feature values differently, but the underlying sample-to-client assignment
remains identical.

## Batch comparison UI and partition stress scenarios

The desktop UI supports selecting any number of algorithms (minimum two) and
running them as one comparison. In federated mode the dataset is partitioned
once, and the exact same client-index lists are reused by every selected
algorithm.

Available partition modes:

- `IID` — random approximately equal client sizes;
- `Dirichlet` — label-skew controlled by alpha;
- `Quantity skew` — unequal client sizes (with five clients the target profile
  is approximately 10/15/20/25/30 percent);
- `Label-limited` — each client is restricted to two classes.

The federated tab shows the realized number of samples and class counts for
every client as soon as the partition is created, before algorithms start.

To keep routine benchmark runs reproducible, several controls are intentionally
fixed instead of editable in the UI: oracle-k, `max_iter=300`,
`DBSCAN min_samples=5`, `min_samples_per_client=3`, and author HF_DBSCAN `MIN_POINTS=4`
`L=0.15`. The existing `RunRequest` fields remain available for programmatic
experiments.

After a comparison finishes, **Export to Excel** creates an `.xlsx` report with
results, the client partition, effective configuration, diagnostics, and the
execution log.

## Scenario 3 — Partial Participation / Dropout

The federated UI exposes two environment controls:

- `Participation, %` — the fraction of clients selected for each benchmark round;
- `Dropout, %` — probability that a selected client fails to return its update.

One schedule is generated from the experiment seed before any algorithm runs and
is reused by every selected algorithm.  The UI and Excel export show, for every
round, the selected, successful, and dropped client IDs.

For iterative algorithms (`fed_kmeans_numpy`, federated FCM/GMM, `Adapted FKM`)
the schedule is consumed round by round.  Author algorithms whose original
protocol is one-shot (`HF_DBSCAN`, `FKDC`, `NN-FC`, `p-FClus`) use the first
round as their one-shot client-availability condition; they are **not** silently
turned into new iterative algorithms.

Flower Simulation variants use the same logical schedule as the NumPy variants.
Because strategy-side Flower proxy IDs cannot be reliably mapped to PyClustEval
partition IDs, all simulator supernodes remain alive while each client enforces
the schedule using its stable `context.node_config["partition-id"]`. Inactive
clients return no-op updates and do not contribute to aggregation. Reported
communication bytes are the logical benchmark payload cost, not packet-level
Flower transport.

## Scenario 4 — Gaussian DP

Federated runs support:

```text
Privacy: None | Gaussian DP
epsilon
delta
clip norm
```

The Gaussian mode is an algorithm-independent benchmark layer.  Each raw feature
vector is L2-clipped, analytic-Gaussian noise is added in **raw feature space**,
and that privatized matrix is sampled once and shared by all selected algorithms.
All communication rounds then operate on the same release, so repeated rounds are
post-processing rather than fresh DP releases.

The adjacency model is replace-one record, with L2 sensitivity `2 * clip_norm`.
No data-dependent global scaler is fitted before the privacy mechanism.  This is
intentional: using non-private statistics estimated from the same private dataset
would invalidate an end-to-end DP claim.

Scope/limitations:

- the privacy layer protects feature matrix `X`; ground-truth labels `y` and the
  benchmark partition metadata are **not** privatized;
- label-based Dirichlet/Label-limited partitions are therefore controlled
  evaluation scenarios, not a claim that the partition itself is private;
- separate independent benchmark runs on the same private data compose privacy
  loss; PyClustEval does not maintain a cross-experiment privacy accountant;
- Secure Aggregation is intentionally not implemented.

The Excel export adds the participation schedule and a dedicated `Privacy` sheet
with epsilon, delta, sensitivity, calibrated sigma, clipping fraction, and scope.


## Generic parameter profile

See `docs/GENERIC_SANE_DEFAULTS.md`. The profile is dataset-agnostic and is not selected by ARI/NMI.
