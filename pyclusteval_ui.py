"""Desktop UI for PyClustEval.

This module contains presentation logic only. Experiment orchestration lives in
``clustering_eval.application.ComparisonService``.
"""

from __future__ import annotations

import queue
import threading
import traceback
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

import numpy as np

from clustering_eval.application import (
    AlgorithmRunReport,
    ComparisonService,
    RunRequest,
)


class ComparisonTab(ttk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        *,
        mode: str,
        datasets: list[str],
        algorithms: list[str],
        on_run: Callable[[RunRequest], None],
    ) -> None:
        super().__init__(master, padding=12)
        self.mode = mode
        self.on_run = on_run

        controls = ttk.LabelFrame(self, text="Параметры сравнения", padding=10)
        controls.pack(fill="x")

        ttk.Label(controls, text="Датасет").grid(row=0, column=0, sticky="w")
        self.dataset = ttk.Combobox(
            controls, values=datasets, state="readonly", width=28
        )
        self.dataset.grid(row=1, column=0, padx=(0, 10), pady=(3, 10), sticky="ew")

        ttk.Label(controls, text="Алгоритм 1").grid(row=0, column=1, sticky="w")
        self.algorithm_1 = ttk.Combobox(
            controls, values=algorithms, state="readonly", width=28
        )
        self.algorithm_1.grid(
            row=1, column=1, padx=(0, 10), pady=(3, 10), sticky="ew"
        )

        ttk.Label(controls, text="Алгоритм 2").grid(row=0, column=2, sticky="w")
        self.algorithm_2 = ttk.Combobox(
            controls, values=algorithms, state="readonly", width=28
        )
        self.algorithm_2.grid(
            row=1, column=2, padx=(0, 10), pady=(3, 10), sticky="ew"
        )

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

            ttk.Label(controls, text="Разбиение").grid(
                row=2, column=2, sticky="w"
            )
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
        self.run_button.grid(
            row=4, column=0, columnspan=4, pady=(14, 0), sticky="ew"
        )

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
        self.table = ttk.Treeview(
            results_box,
            columns=columns,
            show="headings",
            height=8,
        )
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
            "algorithm": 190,
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

        scrollbar = ttk.Scrollbar(
            results_box,
            orient="horizontal",
            command=self.table.xview,
        )
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
        if not all(
            (self.dataset.get(), self.algorithm_1.get(), self.algorithm_2.get())
        ):
            messagebox.showerror("Ошибка", "Выбери датасет и два алгоритма.")
            return
        if self.algorithm_1.get() == self.algorithm_2.get():
            messagebox.showerror("Ошибка", "Для сравнения выбери разные алгоритмы.")
            return

        try:
            request = RunRequest(
                mode=self.mode,  # type: ignore[arg-type]
                dataset_name=self.dataset.get(),
                algorithms=(self.algorithm_1.get(), self.algorithm_2.get()),
                seed=int(self.seed.get()),
                num_clients=int(self.clients.get()),
                partition_mode=self.partition_mode.get(),  # type: ignore[arg-type]
                dirichlet_alpha=float(self.alpha.get()),
            )
            request.validate()
        except ValueError as error:
            messagebox.showerror("Ошибка параметров", str(error))
            return

        self.clear()
        self.set_busy(True)
        self.on_run(request)

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

    def show_results(self, results: list[AlgorithmRunReport]) -> None:
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

        self.service = ComparisonService()
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        self.local_tab = ComparisonTab(
            notebook,
            mode="local",
            datasets=self.service.dataset_names(),
            algorithms=self.service.algorithm_names(federated=False),
            on_run=self.start_run,
        )
        self.federated_tab = ComparisonTab(
            notebook,
            mode="federated",
            datasets=self.service.dataset_names(),
            algorithms=self.service.algorithm_names(federated=True),
            on_run=self.start_run,
        )

        notebook.add(self.local_tab, text="Локальный запуск")
        notebook.add(self.federated_tab, text="Федеративный запуск")
        self.after(100, self._poll_events)

    def start_run(self, request: RunRequest) -> None:
        threading.Thread(
            target=self._run_service,
            args=(request,),
            daemon=True,
        ).start()

    def _run_service(self, request: RunRequest) -> None:
        try:
            report = self.service.compare(
                request,
                on_log=lambda text: self.events.put(
                    ("log", (request.mode, text))
                ),
            )
            self.events.put(("done", (request.mode, report)))
        except Exception:
            self.events.put(
                ("error", (request.mode, traceback.format_exc()))
            )

    def _tab_for_mode(self, mode: str) -> ComparisonTab:
        return self.local_tab if mode == "local" else self.federated_tab

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                mode, value = payload
                tab = self._tab_for_mode(mode)

                if event == "log":
                    tab.append_log(value)
                elif event == "done":
                    report = value
                    tab.show_results(report.results)
                    tab.append_log(
                        "\nСравнение завершено. "
                        f"История: {report.history_directory}\n"
                    )
                    tab.set_busy(False)
                elif event == "error":
                    tab.append_log("\nОШИБКА:\n" + value)
                    tab.set_busy(False)
                    messagebox.showerror(
                        "Ошибка выполнения",
                        "Тест завершился с ошибкой. Подробности находятся в логе.",
                    )
        except queue.Empty:
            pass
        self.after(100, self._poll_events)


if __name__ == "__main__":
    PyClustEvalApp().mainloop()
