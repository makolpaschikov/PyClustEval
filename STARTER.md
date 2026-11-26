# Windows x64: локальные и NumPy-федеративные запуски

После подготовки окружения для проверки кампаний используй [пилоты на Iris и измерение Dry Bean](docs/CAMPAIGN_PROFILE.md).

Открой PowerShell в корне PyClustEval рядом с `pyproject.toml`. Проверенный профиль использует 64-разрядный CPython 3.12.10 с Tcl/Tk, базовые зависимости проекта и pytest. Для точного повтора используй ту же версию интерпретатора.

## Окружение

Проверь зарегистрированные версии командой `py -0p`. Для проверенной установки использовался пакет Python Software Foundation `Python.Python.3.12` версии 3.12.10 из источника WinGet `winget`, архитектура x64, область установки — текущий пользователь, с pip и Tcl/Tk. Если Python уже установлен по известному пути и отсутствует в списке launcher, используй его `python.exe` вместо `py -3.12` в блоке создания среды. Сохрани каталог существующей `.venv` при любом отказе проверки.

```powershell
$python = '.\.venv\Scripts\python.exe'
$venvPath = Join-Path (Get-Location) '.venv'
$platformCheck = "import platform, sys; print(sys.executable, platform.python_version(), platform.machine()); sys.exit(0 if sys.implementation.name == 'cpython' and sys.version_info[:2] == (3, 12) and platform.machine().upper() == 'AMD64' and sys.maxsize > 2**32 else 1)"

if (!(Test-Path -LiteralPath '.venv')) {
    py -3.12 -I -B -c $platformCheck
    if ($LASTEXITCODE -ne 0) { throw 'Требуется CPython 3.12 x64.' }
    py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось создать .venv.' }
}
if (!(Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "В $venvPath отсутствует Scripts\python.exe. Проверь каталог и путь интерпретатора."
}
& $python -I -B -c $platformCheck
if ($LASTEXITCODE -ne 0) { throw "Для $venvPath требуется CPython 3.12 x64." }
& $python -I -B -c "from pathlib import Path; import sys; sys.exit(0 if sys.prefix != sys.base_prefix and Path(sys.prefix).resolve() == Path('.venv').resolve() else 1)"
if ($LASTEXITCODE -ne 0) { throw "Интерпретатор должен принадлежать $venvPath." }
$cfg = Join-Path $venvPath 'pyvenv.cfg'
$siteSetting = @(Get-Content -LiteralPath $cfg -ErrorAction Stop | Where-Object { $_ -match '^\s*include-system-site-packages\s*=' })
if ($siteSetting.Count -ne 1 -or $siteSetting[0] -notmatch '=\s*false\s*$') {
    throw "Для изолированной среды в $cfg должно быть include-system-site-packages = false."
}
& $python -I -B -c "import tkinter, _tkinter"
if ($LASTEXITCODE -ne 0) { throw "CPython для $venvPath должен загружать tkinter и _tkinter." }
& $python -I -B -c "import pip, sys; from pathlib import Path; sys.exit(0 if Path(pip.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Для установки нужен pip из $venvPath." }
```

## Установка

Список прямых зависимостей и extra `dev` определены в `pyproject.toml`. Файл [windows-py312.txt](constraints/windows-py312.txt) фиксирует проверенные версии инструментов сборки, тестовых и научных библиотек с их зависимостями. Первый вызов pip готовит сборочный стек внутри выбранной среды. Второй устанавливает editable-пакет из текущей рабочей копии с этим стеком.

```powershell
$python = '.\.venv\Scripts\python.exe'
$pins = '.\constraints\windows-py312.txt'
& $python -m pip install -c $pins pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw 'Ошибка установки инструментов сборки.' }
& $python -m pip install --no-build-isolation -c $pins -e '.[dev]'
if ($LASTEXITCODE -ne 0) { throw 'Ошибка установки PyClustEval.' }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Обнаружен конфликт зависимостей.' }
```

Повторная установка использует тот же файл версий. `& $python -m pip list --format=freeze` выводит фактический состав среды.

### Изолированная среда Flower

Для профиля Windows cold используй отдельную среду CPython 3.12.10 x64. У Flower 1.41.0 ограничение `packaging<26`, поэтому для этой среды выделен `constraints/windows-flower-py312.txt`. Следующий пример создаёт новую проектную среду, устанавливает полный зафиксированный набор и привязывает исполняемый CLI к текущему checkout.

```powershell
$flowerEnv = '.\.agent-work\tasks\flower-runtime\.venv'
if (Test-Path -LiteralPath $flowerEnv) { throw 'Выбери новый путь для чистой среды или проверь существующую.' }
& $python -m venv $flowerEnv
if ($LASTEXITCODE -ne 0) { throw 'Ошибка создания отдельной среды Flower.' }
$flowerPython = Join-Path $flowerEnv 'Scripts\python.exe'
$flowerPins = '.\constraints\windows-flower-py312.txt'
& $flowerPython -m pip install --only-binary=:all: -r $flowerPins
if ($LASTEXITCODE -ne 0) { throw 'Ошибка установки зафиксированных версий Flower/Ray.' }
& $flowerPython -m pip install --no-build-isolation -c $flowerPins -e '.[flower,dev]'
if ($LASTEXITCODE -ne 0) { throw 'Ошибка установки PyClustEval в среде Flower.' }
& $flowerPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Конфликт зависимостей в среде Flower.' }
```

Проверяй фактический допуск по завершившимся заданиям, полям backend и истории [реального пилота](docs/CAMPAIGN_PROFILE.md).

## Проверка и запуск

```powershell
& '.\.venv\Scripts\python.exe' -c "import numpy, pandas, scipy, sklearn, yaml, tqdm, matplotlib, xlsxwriter, pytest, tkinter, pyclusteval_ui; import clustering_eval; print(clustering_eval.__file__)"
& '.\.venv\Scripts\clustereval.exe' --help
& '.\.venv\Scripts\python.exe' -m pytest -q tests/test_application_smoke.py::test_local_comparison_and_history tests/test_application_smoke.py::test_federated_numpy_comparison
```

Чтобы выполнить одно локальное задание, сохрани свою копию `configs/example.yaml` как `local-run.yaml` в корне проекта. Укажи в ней свободный каталог в поле `experiment.output_dir`, затем запусти первое задание.

```powershell
& '.\.venv\Scripts\clustereval.exe' run '.\local-run.yaml' --limit 1
```

Графическое приложение запускается из этой же среды.

```powershell
& '.\.venv\Scripts\python.exe' '.\pyclusteval_ui.py'
```
