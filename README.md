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

The federated registry also contains four adapters that execute the specific author implementations supplied with this project:

- `Adapted FKM` — swiergarst/fedKMeans
- `Adapted HF_DBSCAN` — GM862001/F_DBSCAN (horizontal implementation)
- `Adapted FKDC` — mlyizhang/FKDC
- `Adapted NN-FC` — mlyizhang/nnfc

See `docs/ADAPTATION.md` for exact source commits, executed files, and every adaptation seam.
