# Проект: clustering-flower-eval

**Версия:** 0.1.0  
**Статус:** MVP (разработка)  
**Последнее обновление:** 2026-07-09

---

## 1. Назначение

Проект представляет собой платформу для воспроизводимого сравнения алгоритмов кластеризации в централизованной и федеративной среде.

**Основные цели:**
- Автоматический запуск большого количества экспериментов
- Единообразное выполнение любых алгоритмов кластеризации
- Поддержка централизованных и федеративных алгоритмов
- Обеспечение воспроизводимости результатов
- Автоматический подсчёт метрик качества
- Единый формат хранения результатов
- Простота расширения функциональности

**Что система НЕ делает:**
- Разработка новых алгоритмов кластеризации
- Обучение моделей вне контекста эксперимента
- Feature engineering
- Хранение больших наборов данных

---

## 2. Архитектурные принципы

1. **Single Responsibility** — каждый модуль имеет одну чётко определённую ответственность
2. **Dependency Inversion** — зависимости строятся на основе абстракций
3. **Plugin Architecture** — новые компоненты добавляются без изменения ядра
4. **Composition over inheritance** — предпочтение композиции перед наследованием
5. **Low Coupling** — минимальная связанность между компонентами
6. **High Cohesion** — высокая внутренняя связанность модулей
7. **Reproducibility First** — воспроизводимость экспериментов превыше всего
8. **Framework Independence** — ядро независимо от конкретных фреймворков

---

## 3. Контекст системы

```
             Пользователь
                  │
             CLI / Python API
                  │
         Experiment Manager
                  │
    ┌─────────────┼─────────────┐
    ▼             ▼             ▼
Dataset      Algorithm      Config
Registry      Registry
    │             │
    └──────┬──────┘
           ▼
 Experiment Planner
           │
           ▼
   Execution Layer
     │          │
 Local      Flower
     │          │
     └────┬─────┘
          ▼
   Metrics Engine
          ▼
 Result Repository
          ▼
 Visualization
```

---

## 4. Основные сущности

### Dataset

Описывает источник данных.

**Поля:**
- `id` — уникальный идентификатор
- `name` — имя датасета
- `features` — признаки (матрица X)
- `labels` — истинные метки (вектор y, опционально)
- `metadata` — дополнительная информация

**Создаётся:** только через DatasetRegistry

---

### Partition

Описывает распределение объектов между клиентами для федеративного обучения.

**Типы разбиений:**
- `IID` — независимое и одинаково распределённое
- `Dirichlet` — не-IID на основе распределения Дирихле (учёт меток)
- `Balanced` — сбалансированное
- `Pathological` — патологическое (неоднородное распределение меток)

---

### Algorithm

Единица вычисления. Алгоритм **не знает**, каким образом он запускается.

**Контракт:**

```python
class ClusteringAlgorithm:
    name: str
    
    def run(
        self, 
        X: np.ndarray, 
        partition: list[np.ndarray] | None, 
        params: dict[str, Any], 
        seed: int
    ) -> AlgorithmResult:
        ...
```

**AlgorithmResult содержит:**
- `labels` — предсказанные метки
- `model_state` — состояние модели (центры, веса и т.д.)
- `history` — история выполнения (для федеративных алгоритмов)
- `runtime_sec` — время выполнения в секундах
- `communication_bytes` — объём коммуникации (для федеративных)

**Алгоритм НЕ имеет права:**
- Сохранять файлы
- Считать метрики
- Обращаться к CLI
- Зависеть от конкретного backend'а выполнения

---

### ExperimentSpec

Описывает конкретный эксперимент (минимальную независимую задачу).

**Поля:**
- `experiment_name` — имя эксперимента
- `dataset_name` — имя датасета
- `dataset_params` — параметры датасета
- `algorithm_name` — имя алгоритма
- `algorithm_params` — параметры алгоритма
- `partition_mode` — режим разбиения (iid/dirichlet)
- `num_clients` — количество клиентов
- `dirichlet_alpha` — параметр альфа для Dirichlet разбиения
- `seed` — начальное значение генератора случайных чисел
- `repetition` — номер повторения

---

### Result

Результат одного эксперимента.

**Содержит:**
- Все поля `ExperimentSpec`
- Значения всех запрошенных метрик (ARI, NMI, Silhouette и т.д.)
- `runtime_sec` — время выполнения
- `communication_bytes` — объём коммуникации (для федеративных)
- `rounds` — количество раундов (для федеративных)
- `n_samples` — количество объектов
- `n_features` — количество признаков

---

## 5. Компоненты

### Dataset Registry

**Ответственность:**
- Загрузка датасетов
- Регистрация новых источников
- Кэширование (планируется)
- Выдача Dataset по имени

**Не знает:**
- Алгоритмов
- Flower
- Метрик

**Доступные датасеты:**
- `iris` — Iris dataset (sklearn)
- `wine` — Wine dataset (sklearn)
- `digits` — Digits dataset (sklearn)
- `blobs` — Синтетические данные (make_blobs)

---

### Partition Manager

**Ответственность:**
- Создание Partition
- Поддержка различных стратегий разбиения

**Не знает:**
- Алгоритмов
- Runner'а
- Flower

---

### Algorithm Registry

**Ответственность:**
- Регистрация алгоритмов
- Хранение экземпляров алгоритмов
- Выдача по имени

**Регистрирует:**
- sklearn-алгоритмы (через адаптеры)
- Flower-адаптеры
- Пользовательские реализации

---

### Experiment Planner

**Получает:**
- Список датасетов
- Список алгоритмов
- Параметры
- Стратегии разбиения
- Seed'ы
- Количество повторений

**Строит:** декартово произведение всех параметров

**На выходе:** список `ExperimentSpec`

---

### Execution Layer

**Задача:** выполнить `ExperimentSpec`

**Поддерживает:**
- `LocalExecution` — локальное выполнение
- `FlowerExecution` — федеративное через Flower (не реализовано)

**Интерфейс:**
```python
class ExecutionBackend:
    def execute(experiment: ExperimentSpec) -> Result:
        ...
```

---

### Metrics Engine

**Получает:**
- `labels_true` — истинные метки (опционально)
- `labels_pred` — предсказанные метки

**Считает:**
- `ari` — Adjusted Rand Index
- `nmi` — Normalized Mutual Information
- `silhouette` — Silhouette Score
- `davies_bouldin` — Davies-Bouldin Index
- `calinski_harabasz` — Calinski-Harabasz Index

**Не выполняет:** алгоритмы кластеризации

---

### Result Repository

**Задача:** сохранение результатов

**Структура:**
```
results/
├── metrics.csv       # сводная таблица результатов
├── history.jsonl     # история экспериментов (line-delimited JSON)
└── [доп. артефакты]  # по необходимости
```

**Формат:**
- CSV для метрик
- JSON Lines для детальной истории

---

## 6. Технологический стек

### Основные зависимости
- **Python >= 3.10**
- **numpy >= 1.24** — численные вычисления
- **pandas >= 2.0** — работа с табличными данными
- **scikit-learn >= 1.3** — алгоритмы кластеризации
- **pyyaml >= 6.0** — парсинг конфигураций

### Опциональные зависимости (с флагом `flower`)
- **flwr[simulation] >= 1.0** — федеративное обучение

---

## 7. Структура проекта

```
clustering_eval/
├── __init__.py
├── cli.py                    # CLI интерфейс
├── datasets/
│   ├── __init__.py
│   ├── base.py              # Dataset dataclass
│   ├── partitioning.py      # Стратегии разбиения (IID, Dirichlet)
│   └── registry.py          # Регистр датасетов
├── algorithms/
│   ├── __init__.py
│   ├── base.py              # ClusteringAlgorithm и AlgorithmResult
│   ├── registry.py          # Регистр алгоритмов
│   ├── sklearn_algorithms.py # Адаптеры sklearn
│   └── fed_kmeans_numpy.py  # Простая федеративная реализация
├── experiments/
│   ├── __init__.py
│   ├── config.py            # Парсинг YAML конфигов
│   ├── planner.py           # Построение плана экспериментов
│   └── runner.py            # Выполнение экспериментов
├── metrics/
│   └── clustering.py        # Подсчёт метрик качества
├── results/
│   └── store.py             # Сохранение результатов
└── flower_adapter/          # Адаптеры для Flower (заглушка)
    ├── __init__.py
    └── fed_kmeans_flower_adapter.py

configs/                     # Примеры конфигураций
results/                     # Результаты экспериментов
openspec/                    # Спецификации проекта
```

---

## 8. Соглашения о коде

### Именование
- **Классы:** PascalCase (`ClusteringAlgorithm`, `DatasetRegistry`)
- **Функции/переменные:** snake_case (`compute_metrics`, `default_registry`)
- **Константы:** UPPER_SNAKE_CASE
- **Модули:** snake_case

### Стиль кода
- Использование type hints (`from __future__ import annotations`)
- Dataclass для неизменяемых структур данных
- Именованные параметры при вызовах
- Комментарии только для "почему", не для "что"

### Обработка ошибок
- Явная проверка аргументов
- Описание доступных опций в сообщениях об ошибках
- Использование исключений стандартных типов

---

## 9. Использование

### Установка

```bash
# Базовая установка
pip install -e .

# С поддержкой Flower
pip install -e '.[flower]'
```

### Запуск эксперимента

```bash
# Через CLI
clustereval run configs/example.yaml

# С ограничением количества экспериментов
clustereval run configs/example.yaml --limit 5
```

### Конфигурация (YAML)

```yaml
experiment:
  name: my_experiment
  seeds: [42, 123]           # начальные значения для воспроизводимости
  repetitions: 3             # количество повторений каждого эксперимента
  output_dir: results        # директория для результатов

datasets:
  - name: iris
  - name: blobs
    params:
      n_samples: 300
      centers: 3

partitioning:
  clients: [5, 10]           # количество клиентов
  modes: [iid, dirichlet]    # режимы разбиения
  dirichlet_alpha: [0.5]     # параметр для не-IID разбиения

algorithms:
  - name: kmeans
    params:
      k: [3, 5]
      max_iter: [100]
  - name: fed_kmeans_numpy
    params:
      k: [3]
      rounds: [10]

metrics:
  - ari
  - nmi
  - silhouette
  - davies_bouldin
  - calinski_harabasz
```

---

## 10. Дорожная карта

### MVP (текущий статус)
- ✅ Локальный runner
- ✅ sklearn алгоритмы
- ⚠️ Flower adapter (частично реализован)
- ✅ CSV результаты

### Ближайшее будущее
- Реализация Flower Execution Layer
- Единый интерфейс алгоритмов (ClusteringAlgorithm)
- Experiment Manager (координатор)
- Dataset Registry (полная реализация)
- Partition Manager (все стратегии)
- Experiment Planner (полная реализация)
- Experiment Runner

### Среднесрочные цели
- Hyperparameter search (Grid/Random/Optuna)
- Parallel execution
- Ray backend
- MPI backend
- Statistical tests
- Dashboard
- HTML/PDF отчёты

---

## 11. Текущий технический долг

См. файл `TECH_DEBT.md` для подробного списка невыполненных обязательств.

**Критично (P0):**
1. Flower Execution Layer
2. Единый интерфейс алгоритмов
3. Experiment Manager

---

## 12. Инварианты архитектуры

Всегда должны соблюдаться:

1. Алгоритм **никогда** не вызывает Flower напрямую
2. Flower **никогда** не считает метрики
3. DatasetRegistry **никогда** не знает об алгоритмах
4. MetricsEngine **никогда** не запускает алгоритмы
5. Planner **никогда** не выполняет вычисления
6. Runner **никогда** не считает метрики
7. ResultRepository **никогда** не вычисляет ничего

---

## 13. Последовательность выполнения эксперимента

1. CLI читает YAML конфигурацию
2. Создаётся `ExperimentRunner`
3. `DatasetRegistry` загружает `Dataset`
4. `PartitionManager` создаёт `Partition`
5. `Planner` строит список `ExperimentSpec`
6. `Runner` берёт следующий `ExperimentSpec`
7. `AlgorithmRegistry` создаёт экземпляр `Algorithm`
8. `ExecutionLayer` запускает алгоритм
9. Получаются предсказанные метки (`labels`)
10. `MetricsEngine` вычисляет показатели качества
11. `ResultStore` сохраняет артефакты (CSV + JSON)
12. Повтор для следующего `ExperimentSpec`

---

## 14. Добавление нового алгоритма

**Разрешается изменять:**
- `algorithms/` — реализация алгоритма
- `configs/` — примеры конфигураций
- `tests/` — тесты

**Запрещается изменять:**
- `planner` — логика планирования
- `metrics` — подсчёт метрик
- `results` — хранение результатов
- `dataset registry` — управление датасетами

**Требования к новому алгоритму:**
- Реализовать интерфейс `ClusteringAlgorithm`
- Поддерживать контракт `run(X, partition, params, seed) -> AlgorithmResult`
- Не зависеть от конкретного backend'а

---

## 15. Лицензия и авторство

Проект разработан в рамках исследовательской работы по сравнению алгоритмов кластеризации.

---

*Документ создан автоматически на основе кода и архитектурных документов проекта.*
