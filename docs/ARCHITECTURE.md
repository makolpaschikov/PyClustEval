# PyClustEval — архитектура приложения

## 1. Назначение

PyClustEval — расширяемое desktop-приложение для сравнения алгоритмов кластеризации в двух режимах:

- локальный запуск;
- федеративный запуск.

Система предоставляет UI, единые реестры датасетов и алгоритмов, воспроизводимое разбиение данных между клиентами, запуск локальных и распределённых backend-реализаций, вычисление метрик и отображение результатов сравнения.

## 2. Архитектурные принципы

### Разделение ответственности

UI отвечает только за выбор параметров, запуск, логирование и отображение результатов. Алгоритмы, partitioning, Flower strategies и метрики находятся в backend-слоях.

### Registry-driven architecture

Доступные сущности определяются через:

- `DatasetRegistry`;
- `AlgorithmRegistry`.

Новый зарегистрированный компонент должен появляться в UI без изменения его кода.

### Единый контракт алгоритма

```python
run(
    X: np.ndarray,
    partition: list[np.ndarray] | None,
    params: dict[str, Any],
    seed: int,
) -> AlgorithmResult
```

Локальный режим использует `partition=None`. Федеративный режим передаёт один и тот же partition обоим сравниваемым алгоритмам.

### Воспроизводимость

В одном эксперименте фиксируются:

- dataset;
- preprocessing;
- seed;
- partition;
- параметры алгоритмов;
- backend;
- environment.

## 3. Presentation Layer

Основной модуль:

```text
pyclusteval_ui.py
```

Компоненты:

- `PyClustEvalApp`;
- `ComparisonTab`;
- tkinter/ttk widgets;
- background worker;
- event queue.

UI создаёт запрос запуска и получает события `log`, `done`, `error`. Tkinter обновляется только из главного потока через `after()`.

## 4. Application / Orchestration Layer

В текущей версии orchestration находится в `PyClustEvalApp._run_comparison()`.

Ответственность:

1. загрузить dataset;
2. выполнить preprocessing;
3. создать partition для федеративного режима;
4. получить алгоритмы из registry;
5. запустить алгоритм 1;
6. вычислить метрики;
7. запустить алгоритм 2;
8. вычислить метрики;
9. сформировать UI result.

Рекомендуемый рефакторинг:

```text
ComparisonService
ExperimentRunner
RunRequest
AlgorithmRunReport
ComparisonReport
```

## 5. Dataset Layer

### DatasetRegistry

```python
names() -> list[str]
load(name: str) -> Dataset
```

Dataset содержит:

```python
dataset.name
dataset.X
dataset.y
```

`y` может отсутствовать.

### Preprocessing

В текущем прототипе используется `StandardScaler`. Обработка выполняется один раз до запуска двух алгоритмов.

## 6. Partitioning Layer

Поддерживаемые режимы:

- IID;
- Dirichlet.

Результат:

```python
list[np.ndarray]
```

Требования:

- детерминированность;
- покрытие всех объектов;
- отсутствие пересечений;
- отсутствие пустых клиентов;
- `partition_fingerprint`.

## 7. Algorithm Layer

### Локальные алгоритмы

Примеры:

- kmeans;
- dbscan;
- gmm;
- agglomerative.

Они получают полный `X` и `partition=None`.

### Федеративные NumPy-алгоритмы

Примеры:

- fed_kmeans_numpy;
- fed_fuzzy_cmeans_numpy;
- fed_gmm_diag_numpy.

Они имитируют клиентов в одном процессе и агрегируют sufficient statistics.

### Федеративные Flower-алгоритмы

Примеры:

- fed_kmeans_flower;
- fed_fuzzy_cmeans_flower;
- fed_gmm_diag_flower.

Они используют:

- ClientApp;
- ServerApp;
- custom Strategy;
- Flower Simulation;
- Ray workers.

## 8. Execution Layer

### Local backend

```text
UI worker
 -> local adapter
 -> sklearn/custom estimator
 -> labels
```

### NumPy federated backend

```text
UI worker
 -> federated adapter
 -> client calculations
 -> server aggregation
 -> global model
 -> labels
```

### Flower backend

```text
UI worker
 -> Flower adapter
 -> ServerApp
 -> Strategy
 -> Ray simulation
 -> ClientApp instances
 -> global model
 -> labels
```

## 9. Metrics Layer

Поддерживаемые метрики:

- Adjusted Rand Index;
- Normalized Mutual Information;
- Silhouette Score;
- Davies–Bouldin Index;
- Calinski–Harabasz Index.

Ошибки отдельных метрик должны изолироваться.

## 10. Result Layer

### AlgorithmResult

```python
labels
model_state
history
runtime_sec
communication_bytes
```

### RunResult

```python
algorithm
backend
runtime_sec
communication_bytes
rounds
ari
nmi
silhouette
davies_bouldin
calinski_harabasz
```

## 11. Локальный поток

1. Пользователь выбирает dataset и два локальных алгоритма.
2. UI создаёт request.
3. Worker загружает и масштабирует dataset.
4. AlgorithmRegistry возвращает adapter.
5. Adapter вызывается с `partition=None`.
6. Metrics Layer рассчитывает показатели.
7. Результат отправляется обратно в UI.

## 12. Федеративный поток

1. Пользователь выбирает dataset, алгоритмы и число клиентов.
2. Worker загружает и масштабирует dataset.
3. Partitioning Layer создаёт partition один раз.
4. Оба алгоритма получают тот же partition.
5. NumPy или Flower backend выполняет федеративные раунды.
6. Backend возвращает labels, history, runtime и communication.
7. Metrics Layer рассчитывает показатели.
8. UI отображает сравнение.

## 13. Ошибки и отказоустойчивость

Нужно обрабатывать:

- неизвестный dataset;
- неизвестный algorithm;
- пустой client partition;
- некорректный alpha;
- отсутствие Flower/Ray;
- падение клиента;
- NaN/Inf;
- один кластер;
- ошибки метрик;
- несовместимые параметры.

UI должен всегда разблокировать кнопку запуска и сохранять traceback в логе.

## 14. Рекомендуемая структура проекта

```text
PyClustEval/
├── pyclusteval_ui.py
├── clustering_eval/
│   ├── application/
│   ├── algorithms/
│   ├── datasets/
│   ├── execution/
│   ├── flower_adapter/
│   ├── metrics/
│   ├── results/
│   └── config/
├── tests/
└── docs/
```

## 15. Следующие улучшения

1. Вынести orchestration из UI.
2. Добавить typed DTO.
3. Сохранять результаты в JSON/CSV.
4. Добавить историю экспериментов.
5. Добавить настройку параметров алгоритмов.
6. Поддержать repeats и confidence intervals.
7. Добавить графики.
8. Добавить cancellation token.
9. Добавить structured logging.
10. Управлять lifecycle Ray.
11. Отделить simulation от production federation.
