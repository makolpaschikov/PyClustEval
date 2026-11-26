# Измерение локальной кампании на Windows

## Пилот на Iris

Открой PowerShell в корне рабочего checkout. Команды используют CPython 3.12 x64 и подготовленное [окружение проекта](../STARTER.md). При первом запуске укажи новые каталоги для вывода. Для повторного чтения существующих результатов укажи их текущие пути.

```powershell
$python = '.\.venv\Scripts\python.exe'
$plan = '.\configs\series\pilot.yaml'
$campaign = '.\results\iris-pilot'
& $python -B -m tools.campaign_profile.observations host . > iris-host.json
& $python -B -m clustering_eval.cli series validate $plan --json
& $python -B -m clustering_eval.cli series plan $plan --output iris-plan.json --json
& $python -B -m clustering_eval.cli series run $plan --json
& $python -B -m clustering_eval.cli series status $campaign --json
& $python -B -m clustering_eval.cli series resume $campaign --json
& $python -B -m clustering_eval.cli series export $campaign --json
& $python -B -m tools.campaign_profile.observations campaign $campaign > iris-resources.json
if (Test-Path -LiteralPath '.\results\portable-iris') { throw 'Укажи новый путь для перенесённого архива.' }
Copy-Item "$campaign\archive" '.\results\portable-iris' -Recurse -ErrorAction Stop
& $python -B -m clustering_eval.cli series verify '.\results\portable-iris' --json
& $python -B '.\results\portable-iris\merge_history.py' --into '.\results\pilot-history'
& $python -B '.\tools\rebuild_validation_from_history.py' '.\results\portable-iris' '.\results\pilot-analysis'
```

Для копирования используй новый путь назначения. В JSON проверяй результат команды и счётчики. Код 0 указывает на успех команды. Статус доступен и для незавершённой кампании. Коды 2, 3 и 4, выборочный повтор и восстановление описаны в [руководстве по очереди](CAMPAIGN_RUNNER.md). При тайм-ауте одного задания посмотри причину в status и идентификатор job в raw/resolved_plan.json. Для явного повтора конкретного задания используй его фактический идентификатор.

```powershell
& $python -B -m clustering_eval.cli series retry $campaign --status timeout --job-id $jobId --timeout-sec 90 --json
```

Базовый план содержит 6 сравнений и 12 заданий с seeds 17 и 43, включая Dirichlet-разбиение с participation 0.8 и dropout 0.2. [Научный пилот](../configs/series/profile/iris-science.yaml) даёт ещё 11 заданий на Iris в отдельной кампании: 5 исходных адаптированных методов, 2 метода на общем выпуске input-DP, по 2 метода в aggregate-DP и согласованном контроле с clipping. Подставь этот файл вместо `$plan` и `.\results\iris-science` вместо `$campaign`. При сравнении смотри тип backend, фактический механизм, сведения обо всех попытках, наблюдавшиеся выпуски и их область действия. Повторный aggregate-DP запуск может дать другие метки.

## Flower и Dry Bean

До полноразмерных замеров используй [малый план Flower на Iris](../configs/series/profile/iris-flower.yaml). В нём три отдельных задания выполняют K-Means, Fuzzy C-Means и diagonal GMM на CPU. Укажи этот план в командах validate, plan и run выше и вызывай их интерпретатором выделенной среды. Сверь фактические backend, результаты и состояние очереди. Статус skipped содержит причину отсутствия допуска. Возможность запуска устанавливается по реальной simulation в выбранном окружении.

Допуск трёх Flower-методов проверен для обычной кампании с `privacy_mode: none`, профилем `cold`, одним worker и одним потоком BLAS. Параметры каждого Ray-клиента — `client_cpus: 1` и `client_gpus: 0`. Доступны правила остановки `current_gui` и `historical_paper`. Среда пилота — Windows x64 build 26200, CPython 3.12.10, Flower 1.41.0, Ray 2.55.1. Исполнитель также сверяет версии grpcio, grpcio-health-checking, protobuf, NumPy, SciPy и scikit-learn c файлом версий отдельной среды. Для Flower с DP, архивного persistent_worker, warm и других непроверенных сочетаний поддержка остаётся открытой.

Замер использует полный архивный Dry Bean, сценарий drybean1/iid_full с seed 17, 10 клиентами и полным участием. Запускаются последовательно Adapted NN-FC, Adapted FKDC и fed_gmm_diag_flower. Свежий рабочий процесс Windows получает одно задание. Для GMM требуется отдельно проверенное окружение Flower/Ray. Ограничения ресурсов охватывают 600 секунд и 6144 МиБ Windows job commit на задание. Все три задания и подготовка используют один календарный бюджет 1800 секунд. При исчерпании бюджета инструмент завершает принадлежащее замеру дерево процессов. Full-archive, warm и parallel повторы в этот план не входят.

Из корня checkout задай `$archive` как каталог исходной статьи с историческим manifest.json. Укажи `$flowerPython` как путь к интерпретатору выделенной Windows-среды. Отдельная предварительная проверка создаёт новый каталог, сверяет данные, применимые параметры, preprocessing, индексы клиентов и расписание. Алгоритмы она не запускает.

```powershell
& $flowerPython -B -m tools.campaign_profile.drybean preflight $archive '.\results\bean-check'
```

Следующая команда выполняет согласованный замер один раз.

```powershell
& $flowerPython -B -m tools.campaign_profile.drybean measure $archive '.\results\bean-measurement'
```

В пределах общего бюджета проверка сохраняет в `inputs/operator-source/` снимок кода, включая `drybean.py` и `observations.py`. Файл `inputs/preflight.json` указывает его идентификатор и Git HEAD. Архив, хэши обоих скриптов и патч можно проверить после переноса по [инструкции для снимков исходников](EXPERIMENT_SOURCE_CAPTURE.md).

Проверка входов повторяется внутри общего срока. Оба действия требуют нового каталога вне исторического архива. При расхождении научных условий информация остаётся в preflight.err и вычисления не начинаются. В режиме measure файлы budget.json и host.json фиксируют условия до работы. В inputs/preflight.json находятся сверенные параметры каждого метода. В measurement.json сохраняются затраченное время, фактический исход фаз, состояние очереди, принятые результаты и причины неполноты. Вывод CLI хранится в run.out/run.err; при наличии журнала исходные попытки остаются в inputs/campaign. Если общий срок прервал supervisor между записями журнала, смотри также причину окончания внешнего процесса в stages и сохранённую последнюю запись задания. Новый каталог или resume после исчерпания срока потребуют нового бюджета.

Для интерпретации используй worker_wall_sec по каждой попытке, algorithm_wall_sec, runtime_sec и preprocessing_sec для принятых результатов. shared_setup_sec относится к общей подготовке сравнения. Отдельное время инфраструктуры может отсутствовать. Пик commit Windows Job Object включает дерево процессов. Физическая память измеряется выборочно суммой working set членов дерева; общие страницы могут учитываться несколько раз. В tree_resources доступны интервал и полнота измерений. Снимок host.json относится к моменту до запуска. Сопоставляй наблюдения одного метода только при совпадении данных, научных условий, backend и профиля исполнения. Три последовательных задания дают по одному наблюдению на метод.
