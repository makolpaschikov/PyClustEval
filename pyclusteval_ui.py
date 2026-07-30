"""
Desktop UI for PyClustEval.

Features:
- Local and federated comparison tabs
- Automatic discovery of registered datasets and algorithms
- Dataset partitioning is performed inside the application
- Federated client count selector
- Background execution so the UI does not freeze
- Result table and execution log

Run from the project root:

    python pyclusteval_ui.py
"""

from __future__ import annotations

import inspect
import queue
import threading
import time
import traceback
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk
from typing import Any, Callable

import numpy as np
from sklearn.preprocessing import StandardScaler

from clustering_eval.algorithms.registry import default_registry as algorithm_registry
from clustering_eval.datasets.partitioning import make_partition, partition_fingerprint
from clustering_eval.datasets.registry import default_registry as dataset_registry
from clustering_eval.metrics.clustering import compute_metrics


METRICS = (
    "ari",
    "nmi",
    "silhouette",
    "davies_bouldin",
    "calinski_harabasz",
)


@dataclass
class RunResult:
    algorithm: str
    backend: str
    runtime_sec: float
    communication_bytes: int
    rounds: int | str
    ari: float | None
    nmi: float | None
    silhouette: float | None
    davies_bouldin: float | None
    calinski_harabasz: float | None


def _registry_names(registry: Any) -> list[str]:
    """Extract names from slightly different registry implementations."""
    for attr in ("names", "list", "keys", "available"):
        member = getattr(registry, attr, None)
        if member is None:
            continue
        value = member() if callable(member) else member
        if isinstance(value, dict):
            return sorted(str(item) for item in value.keys())
        try:
            return sorted(str(item) for item in value)
        except TypeError:
            pass

    for attr in ("_items", "_registry", "_algorithms", "_datasets"):
        value = getattr(registry, attr, None)
        if isinstance(value, dict):
            return sorted(str(item) for item in value.keys())

    raise RuntimeError(
        f"Cannot discover entries from registry {type(registry).__name__}. "
        "Add a names(), keys(), list(), or available() method."
    )


def _get_registry_item(registry: Any, name: str) -> Any:
    for method_name in ("get", "load", "create"):
        method = getattr(registry, method_name, None)
        if callable(method):
            try:
                return method(name)
            except (KeyError, TypeError, ValueError):
                continue

    for attr in ("_items", "_registry", "_algorithms", "_datasets"):
        mapping = getattr(registry, attr, None)
        if isinstance(mapping, dict) and name in mapping:
            return mapping[name]

    raise KeyError(f"Registry entry not found: {name}")


def _is_federated(name: str, algorithm: Any) -> bool:
    """Prefer explicit metadata; fall back to conventional registered names."""
    for attr in ("is_federated", "federated"):
        value = getattr(algorithm, attr, None)
        if value is not None:
            return bool(value)

    backend = str(getattr(algorithm, "backend", "")).lower()
    execution_backend = str(getattr(algorithm, "execution_backend", "")).lower()
    lowered = name.lower()

    return (
        lowered.startswith("fed_")
        or "federated" in lowered
        or "flower" in lowered
        or "federated" in backend
        or "flower" in backend
        or "federated" in execution_backend
        or "flower" in execution_backend
    )


def _load_dataset(registry: Any, name: str) -> Any:
    load = getattr(registry, "load", None)
    if callable(load):
        return load(name)

    item = _get_registry_item(registry, name)
    if callable(item):
        return item()
    return item


def _extract_xy(dataset: Any) -> tuple[np.ndarray, np.ndarray | None, str]:
    if hasattr(dataset, "X"):
        X = np.asarray(dataset.X)
        y = None if getattr(dataset, "y", None) is None else np.asarray(dataset.y)
        name = str(getattr(dataset, "name", "dataset"))
        return X, y, name

    if isinstance(dataset, tuple) and len(dataset) >= 1:
        X = np.asarray(dataset[0])
        y = None if len(dataset) < 2 or dataset[1] is None else np.asarray(dataset[1])
        return X, y, "dataset"

    raise TypeError("Dataset must expose X and optional y attributes or return (X, y).")


def _invoke_algorithm(
    algorithm: Any,
    *,
    X: np.ndarray,
    partition: Any | None,
    params: dict[str, Any],
    seed: int,
) -> Any:
    run: Callable[..., Any] | None = getattr(algorithm, "run", None)
    if run is None and callable(algorithm):
        run = algorithm
    if run is None:
        raise TypeError(f"{type(algorithm).__name__} has no run() method")

    signature = inspect.signature(run)
    accepted = set(signature.parameters)
    kwargs: dict[str, Any] = {}

    aliases = {
        "X": X,
        "x": X,
        "data": X,
        "partition": partition,
        "partitions": partition,
        "client_partitions": partition,
        "params": params,
        "parameters": params,
        "seed": seed,
        "random_state": seed,
    }

    has_var_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )

    for key, value in aliases.items():
        if value is not None and (has_var_kwargs or key in accepted):
            kwargs[key] = value

    try:
        return run(**kwargs)
    except TypeError as first_error:
        # Compatibility fallback for simple adapters using positional X.
        try:
            if partition is None:
                return run(X, params=params, seed=seed)
            return run(X, partition=partition, params=params, seed=seed)
        except TypeError:
            raise first_error


def _extract_result(result: Any) -> tuple[np.ndarray, float, int, dict[str, Any], list[Any]]:
    labels = getattr(result, "labels", None)
    if labels is None and isinstance(result, np.ndarray):
        labels = result
    if labels is None:
        raise TypeError("Algorithm result does not contain labels")

    runtime = float(getattr(result, "runtime_sec", 0.0))
    communication = int(getattr(result, "communication_bytes", 0))
    state = getattr(result, "model_state", {}) or {}
    history = getattr(result, "history", []) or []
    return np.asarray(labels), runtime, communication, dict(state), list(history)


class ComparisonTab(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        mode: str,
        datasets: list[str],
        algorithms: list[str],
        on_run: Callable[[dict[str, Any]], None],
    ) -> None:
        super().__init__(master, padding=12)
        self.mode = mode
        self.on_run = on_run

        controls = ttk.LabelFrame(self, text="Параметры сравнения", padding=10)
        controls.pack(fill="x")

        ttk.Label(controls, text="Датасет").grid(row=0, column=0, sticky="w")
        self.dataset = ttk.Combobox(controls, values=datasets, state="readonly", width=28)
        self.dataset.grid(row=1, column=0, padx=(0, 10), pady=(3, 10), sticky="ew")

        ttk.Label(controls, text="Алгоритм 1").grid(row=0, column=1, sticky="w")
        self.algorithm_1 = ttk.Combobox(
            controls, values=algorithms, state="readonly", width=28
        )
        self.algorithm_1.grid(row=1, column=1, padx=(0, 10), pady=(3, 10), sticky="ew")

        ttk.Label(controls, text="Алгоритм 2").grid(row=0, column=2, sticky="w")
        self.algorithm_2 = ttk.Combobox(
            controls, values=algorithms, state="readonly", width=28
        )
        self.algorithm_2.grid(row=1, column=2, padx=(0, 10), pady=(3, 10), sticky="ew")

        ttk.Label(controls, text="Seed").grid(row=2, column=0, sticky="w")
        self.seed = tk.StringVar(value="42")
        ttk.Entry(controls, textvariable=self.seed, width=12).grid(
            row=3, column=0, padx=(0, 10), sticky="w"
        )

        self.clients = tk.StringVar(value="5")
        self.partition_mode = tk.StringVar(value="iid")
        self.alpha = tk.StringVar(value="0.5")

        if mode == "federated":
            ttk.Label(controls, text="Количество клиентов").grid(
                row=2, column=1, sticky="w"
            )
            ttk.Spinbox(
                controls,
                from_=2,
                to=100,
                textvariable=self.clients,
                width=12,
            ).grid(row=3, column=1, padx=(0, 10), sticky="w")

            ttk.Label(controls, text="Разбиение").grid(row=2, column=2, sticky="w")
            ttk.Combobox(
                controls,
                textvariable=self.partition_mode,
                values=("iid", "dirichlet"),
                state="readonly",
                width=15,
            ).grid(row=3, column=2, padx=(0, 10), sticky="w")

            ttk.Label(controls, text="Dirichlet alpha").grid(
                row=2, column=3, sticky="w"
            )
            ttk.Entry(controls, textvariable=self.alpha, width=12).grid(
                row=3, column=3, sticky="w"
            )

        self.run_button = ttk.Button(
            controls,
            text="Запустить сравнение",
            command=self._submit,
        )
        self.run_button.grid(row=4, column=0, columnspan=4, pady=(14, 0), sticky="ew")

        for column in range(4):
            controls.columnconfigure(column, weight=1)

        results_box = ttk.LabelFrame(self, text="Результаты", padding=8)
        results_box.pack(fill="both", expand=True, pady=(12, 0))

        columns = (
            "algorithm",
            "backend",
            "runtime",
            "communication",
            "rounds",
            "ari",
            "nmi",
            "silhouette",
            "db",
            "ch",
        )
        self.table = ttk.Treeview(results_box, columns=columns, show="headings", height=8)
        headings = {
            "algorithm": "Алгоритм",
            "backend": "Backend",
            "runtime": "Время, сек",
            "communication": "Трафик, байт",
            "rounds": "Раунды",
            "ari": "ARI",
            "nmi": "NMI",
            "silhouette": "Silhouette",
            "db": "Davies-Bouldin",
            "ch": "Calinski-Harabasz",
        }
        widths = {
            "algorithm": 180,
            "backend": 150,
            "runtime": 90,
            "communication": 110,
            "rounds": 70,
            "ari": 80,
            "nmi": 80,
            "silhouette": 90,
            "db": 110,
            "ch": 130,
        }
        for column in columns:
            self.table.heading(column, text=headings[column])
            self.table.column(column, width=widths[column], anchor="center")

        scrollbar = ttk.Scrollbar(results_box, orient="horizontal", command=self.table.xview)
        self.table.configure(xscrollcommand=scrollbar.set)
        self.table.pack(fill="both", expand=True)
        scrollbar.pack(fill="x")

        ttk.Label(results_box, text="Лог").pack(anchor="w", pady=(10, 3))
        self.log = tk.Text(results_box, height=8, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True)

        if datasets:
            self.dataset.current(0)
        if algorithms:
            self.algorithm_1.current(0)
            self.algorithm_2.current(1 if len(algorithms) > 1 else 0)

    def _submit(self) -> None:
        if not self.dataset.get() or not self.algorithm_1.get() or not self.algorithm_2.get():
            messagebox.showerror("Ошибка", "Выбери датасет и два алгоритма.")
            return
        if self.algorithm_1.get() == self.algorithm_2.get():
            messagebox.showerror("Ошибка", "Для сравнения выбери разные алгоритмы.")
            return

        try:
            payload = {
                "mode": self.mode,
                "dataset": self.dataset.get(),
                "algorithms": [self.algorithm_1.get(), self.algorithm_2.get()],
                "seed": int(self.seed.get()),
                "clients": int(self.clients.get()),
                "partition_mode": self.partition_mode.get(),
                "alpha": float(self.alpha.get()),
            }
        except ValueError:
            messagebox.showerror("Ошибка", "Seed, клиенты и alpha должны быть числами.")
            return

        self.clear()
        self.set_busy(True)
        self.on_run(payload)

    def set_busy(self, busy: bool) -> None:
        self.run_button.configure(
            state="disabled" if busy else "normal",
            text="Выполняется…" if busy else "Запустить сравнение",
        )

    def clear(self) -> None:
        for item in self.table.get_children():
            self.table.delete(item)
        self.set_log("")

    def set_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("end", text)
        self.log.configure(state="disabled")

    def append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    @staticmethod
    def _fmt(value: Any) -> str:
        if value is None:
            return "—"
        if isinstance(value, float):
            if np.isnan(value):
                return "—"
            return f"{value:.4f}"
        return str(value)

    def show_results(self, results: list[RunResult]) -> None:
        for result in results:
            self.table.insert(
                "",
                "end",
                values=(
                    result.algorithm,
                    result.backend,
                    self._fmt(result.runtime_sec),
                    result.communication_bytes,
                    result.rounds,
                    self._fmt(result.ari),
                    self._fmt(result.nmi),
                    self._fmt(result.silhouette),
                    self._fmt(result.davies_bouldin),
                    self._fmt(result.calinski_harabasz),
                ),
            )


class PyClustEvalApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PyClustEval — сравнение алгоритмов")
        self.geometry("1250x760")
        self.minsize(1000, 650)

        self.algorithm_registry = algorithm_registry()
        self.dataset_registry = dataset_registry()
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()

        dataset_names = _registry_names(self.dataset_registry)
        algorithm_names = _registry_names(self.algorithm_registry)

        local_names: list[str] = []
        federated_names: list[str] = []
        for name in algorithm_names:
            item = _get_registry_item(self.algorithm_registry, name)
            if _is_federated(name, item):
                federated_names.append(name)
            else:
                local_names.append(name)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        self.local_tab = ComparisonTab(
            notebook,
            mode="local",
            datasets=dataset_names,
            algorithms=local_names,
            on_run=self.start_run,
        )
        self.federated_tab = ComparisonTab(
            notebook,
            mode="federated",
            datasets=dataset_names,
            algorithms=federated_names,
            on_run=self.start_run,
        )

        notebook.add(self.local_tab, text="Локальный запуск")
        notebook.add(self.federated_tab, text="Федеративный запуск")

        self.after(100, self._poll_events)

    def start_run(self, payload: dict[str, Any]) -> None:
        thread = threading.Thread(
            target=self._run_comparison,
            args=(payload,),
            daemon=True,
        )
        thread.start()

    def _emit_log(self, mode: str, text: str) -> None:
        self.events.put(("log", (mode, text)))

    def _run_comparison(self, payload: dict[str, Any]) -> None:
        mode = payload["mode"]
        try:
            self._emit_log(mode, f"Загрузка датасета {payload['dataset']}…\n")
            dataset = _load_dataset(self.dataset_registry, payload["dataset"])
            X_raw, y, dataset_name = _extract_xy(dataset)
            X = StandardScaler().fit_transform(np.asarray(X_raw, dtype=np.float64))

            partition = None
            if mode == "federated":
                self._emit_log(
                    mode,
                    f"Внутреннее разбиение датасета на {payload['clients']} клиентов…\n",
                )
                partition = make_partition(
                    mode=payload["partition_mode"],
                    n_samples=len(X),
                    num_clients=payload["clients"],
                    seed=payload["seed"],
                    y=y,
                    alpha=payload["alpha"],
                )
                counts = [len(indices) for indices in partition]
                fingerprint = partition_fingerprint(partition)
                self._emit_log(mode, f"Partition ID: {fingerprint}\n")
                self._emit_log(mode, f"Размеры клиентов: {counts}\n")

            results: list[RunResult] = []
            default_params = {
                "k": len(np.unique(y)) if y is not None else 3,
                "n_clusters": len(np.unique(y)) if y is not None else 3,
                "rounds": 10,
                "tol": 1e-4,
                "client_cpus": 1.0,
                "client_gpus": 0.0,
            }

            for name in payload["algorithms"]:
                self._emit_log(mode, f"\nЗапуск {name}…\n")
                algorithm = _get_registry_item(self.algorithm_registry, name)

                started = time.perf_counter()
                raw_result = _invoke_algorithm(
                    algorithm,
                    X=X,
                    partition=partition,
                    params=default_params,
                    seed=payload["seed"],
                )
                elapsed = time.perf_counter() - started

                labels, runtime, communication, state, history = _extract_result(raw_result)
                if runtime <= 0:
                    runtime = elapsed

                metrics = compute_metrics(
                    X=X,
                    y_true=y,
                    y_pred=labels,
                    requested=list(METRICS),
                )

                backend = str(
                    state.get(
                        "backend",
                        "local" if mode == "local" else "federated",
                    )
                )
                rounds: int | str = state.get("rounds", len(history) if history else "—")

                results.append(
                    RunResult(
                        algorithm=name,
                        backend=backend,
                        runtime_sec=runtime,
                        communication_bytes=communication,
                        rounds=rounds,
                        ari=metrics.get("ari"),
                        nmi=metrics.get("nmi"),
                        silhouette=metrics.get("silhouette"),
                        davies_bouldin=metrics.get("davies_bouldin"),
                        calinski_harabasz=metrics.get("calinski_harabasz"),
                    )
                )
                self._emit_log(mode, f"{name} завершён за {runtime:.4f} сек.\n")

            self.events.put(("done", (mode, results)))
        except Exception:
            self.events.put(("error", (mode, traceback.format_exc())))

    def _tab_for_mode(self, mode: str) -> ComparisonTab:
        return self.local_tab if mode == "local" else self.federated_tab

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "log":
                    mode, text = payload
                    self._tab_for_mode(mode).append_log(text)
                elif event == "done":
                    mode, results = payload
                    tab = self._tab_for_mode(mode)
                    tab.show_results(results)
                    tab.append_log("\nСравнение завершено.\n")
                    tab.set_busy(False)
                elif event == "error":
                    mode, error = payload
                    tab = self._tab_for_mode(mode)
                    tab.append_log("\nОШИБКА:\n" + error)
                    tab.set_busy(False)
                    messagebox.showerror(
                        "Ошибка выполнения",
                        "Тест завершился с ошибкой. Подробности находятся в логе.",
                    )
        except queue.Empty:
            pass
        self.after(100, self._poll_events)


if __name__ == "__main__":
    app = PyClustEvalApp()
    app.mainloop()
