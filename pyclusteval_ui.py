"""Desktop UI for PyClustEval.

This module contains presentation logic only. Experiment orchestration and
history access live in ``clustering_eval.application`` services.
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
    HistoryExperimentDetails,
    HistoryExperimentSummary,
    HistoryQueryService,
    RunRequest,
)


RESULT_COLUMNS = (
    "algorithm", "backend", "runtime", "communication", "rounds",
    "ari", "nmi", "silhouette", "db", "ch",
)
RESULT_HEADINGS = {
    "algorithm": "Алгоритм", "backend": "Backend", "runtime": "Время, сек",
    "communication": "Трафик, байт", "rounds": "Раунды", "ari": "ARI",
    "nmi": "NMI", "silhouette": "Silhouette", "db": "Davies-Bouldin",
    "ch": "Calinski-Harabasz",
}
RESULT_WIDTHS = {
    "algorithm": 190, "backend": 150, "runtime": 90, "communication": 110,
    "rounds": 70, "ari": 80, "nmi": 80, "silhouette": 90, "db": 110,
    "ch": 130,
}


def _create_results_table(master: tk.Misc, *, height: int = 8) -> ttk.Treeview:
    table = ttk.Treeview(master, columns=RESULT_COLUMNS, show="headings", height=height)
    for column in RESULT_COLUMNS:
        table.heading(column, text=RESULT_HEADINGS[column])
        table.column(column, width=RESULT_WIDTHS[column], anchor="center")
    return table


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        if np.isnan(value):
            return "—"
        return f"{value:.4f}"
    return str(value)


def _insert_results(table: ttk.Treeview, results: list[AlgorithmRunReport]) -> None:
    for item in table.get_children():
        table.delete(item)
    for result in results:
        table.insert("", "end", values=(
            result.algorithm, result.backend, _fmt(result.runtime_sec),
            result.communication_bytes, result.rounds, _fmt(result.ari),
            _fmt(result.nmi), _fmt(result.silhouette),
            _fmt(result.davies_bouldin), _fmt(result.calinski_harabasz),
        ))


class ComparisonTab(ttk.Frame):
    def __init__(self, master: tk.Misc, *, mode: str, datasets: list[str],
                 algorithms: list[str], on_run: Callable[[RunRequest], None]) -> None:
        super().__init__(master, padding=12)
        self.mode = mode
        self.on_run = on_run
        controls = ttk.LabelFrame(self, text="Параметры сравнения", padding=10)
        controls.pack(fill="x")

        ttk.Label(controls, text="Датасет").grid(row=0, column=0, sticky="w")
        self.dataset = ttk.Combobox(controls, values=datasets, state="readonly", width=28)
        self.dataset.grid(row=1, column=0, padx=(0, 10), pady=(3, 10), sticky="ew")
        ttk.Label(controls, text="Алгоритм 1").grid(row=0, column=1, sticky="w")
        self.algorithm_1 = ttk.Combobox(controls, values=algorithms, state="readonly", width=28)
        self.algorithm_1.grid(row=1, column=1, padx=(0, 10), pady=(3, 10), sticky="ew")
        ttk.Label(controls, text="Алгоритм 2").grid(row=0, column=2, sticky="w")
        self.algorithm_2 = ttk.Combobox(controls, values=algorithms, state="readonly", width=28)
        self.algorithm_2.grid(row=1, column=2, padx=(0, 10), pady=(3, 10), sticky="ew")

        ttk.Label(controls, text="Seed").grid(row=2, column=0, sticky="w")
        self.seed = tk.StringVar(value="42")
        ttk.Entry(controls, textvariable=self.seed, width=12).grid(row=3, column=0, padx=(0, 10), sticky="w")
        self.clients = tk.StringVar(value="5")
        self.partition_mode = tk.StringVar(value="iid")
        self.alpha = tk.StringVar(value="0.5")

        if mode == "federated":
            ttk.Label(controls, text="Количество клиентов").grid(row=2, column=1, sticky="w")
            ttk.Spinbox(controls, from_=2, to=100, textvariable=self.clients, width=12).grid(row=3, column=1, padx=(0, 10), sticky="w")
            ttk.Label(controls, text="Разбиение").grid(row=2, column=2, sticky="w")
            ttk.Combobox(controls, textvariable=self.partition_mode, values=("iid", "dirichlet"), state="readonly", width=15).grid(row=3, column=2, padx=(0, 10), sticky="w")
            ttk.Label(controls, text="Dirichlet alpha").grid(row=2, column=3, sticky="w")
            ttk.Entry(controls, textvariable=self.alpha, width=12).grid(row=3, column=3, sticky="w")

        self.run_button = ttk.Button(controls, text="Запустить сравнение", command=self._submit)
        self.run_button.grid(row=4, column=0, columnspan=4, pady=(14, 0), sticky="ew")
        for column in range(4):
            controls.columnconfigure(column, weight=1)

        results_box = ttk.LabelFrame(self, text="Результаты", padding=8)
        results_box.pack(fill="both", expand=True, pady=(12, 0))
        self.table = _create_results_table(results_box)
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
        if not all((self.dataset.get(), self.algorithm_1.get(), self.algorithm_2.get())):
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
        self.run_button.configure(state="disabled" if busy else "normal", text="Выполняется…" if busy else "Запустить сравнение")

    def clear(self) -> None:
        _insert_results(self.table, [])
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

    def show_results(self, results: list[AlgorithmRunReport]) -> None:
        _insert_results(self.table, results)


class HistoryTab(ttk.Frame):
    def __init__(self, master: tk.Misc, *, on_refresh: Callable[[], None],
                 on_select: Callable[[str], None]) -> None:
        super().__init__(master, padding=12)
        self.on_refresh = on_refresh
        self.on_select = on_select
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 8))
        self.refresh_button = ttk.Button(toolbar, text="Обновить историю", command=self.on_refresh)
        self.refresh_button.pack(side="left")
        self.status = ttk.Label(toolbar, text="")
        self.status.pack(side="left", padx=12)

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)
        list_box = ttk.LabelFrame(body, text="Сравнения", padding=8)
        details_box = ttk.LabelFrame(body, text="Детали", padding=8)
        body.add(list_box, weight=1)
        body.add(details_box, weight=2)

        columns = ("date", "mode", "dataset", "algorithms", "duration")
        self.history_table = ttk.Treeview(list_box, columns=columns, show="headings", selectmode="browse")
        for column, title, width in (
            ("date", "Дата", 155), ("mode", "Режим", 90), ("dataset", "Датасет", 120),
            ("algorithms", "Алгоритмы", 260), ("duration", "Время, сек", 90),
        ):
            self.history_table.heading(column, text=title)
            self.history_table.column(column, width=width, anchor="center")
        self.history_table.pack(fill="both", expand=True)
        self.history_table.bind("<<TreeviewSelect>>", self._selection_changed)

        self.summary = tk.StringVar(value="Выбери эксперимент слева.")
        ttk.Label(details_box, textvariable=self.summary, justify="left").pack(anchor="w", fill="x", pady=(0, 8))
        self.results_table = _create_results_table(details_box, height=6)
        xscroll = ttk.Scrollbar(details_box, orient="horizontal", command=self.results_table.xview)
        self.results_table.configure(xscrollcommand=xscroll.set)
        self.results_table.pack(fill="both", expand=True)
        xscroll.pack(fill="x")
        ttk.Label(details_box, text="Лог эксперимента").pack(anchor="w", pady=(10, 3))
        self.log = tk.Text(details_box, height=10, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True)

    def set_busy(self, busy: bool, text: str = "") -> None:
        self.refresh_button.configure(state="disabled" if busy else "normal")
        self.status.configure(text=text)

    def show_summaries(self, summaries: list[HistoryExperimentSummary]) -> None:
        for item in self.history_table.get_children():
            self.history_table.delete(item)
        for summary in summaries:
            self.history_table.insert("", "end", iid=summary.history_key, values=(
                summary.started_at.strftime("%Y-%m-%d %H:%M:%S"),
                "Локальный" if summary.mode == "local" else "Федеративный",
                summary.dataset_name,
                " vs ".join(summary.algorithms),
                f"{summary.duration_sec:.3f}",
            ))
        self.status.configure(text=f"Экспериментов: {len(summaries)}")
        if summaries:
            first = summaries[0].history_key
            self.history_table.selection_set(first)
            self.history_table.focus(first)
            self.on_select(first)
        else:
            self.clear_details("История пока пуста.")

    def show_details(self, details: HistoryExperimentDetails) -> None:
        partition_text = ""
        if details.partition is not None:
            partition_text = (
                f" | клиентов: {details.partition.num_clients}"
                f" | partition: {details.partition.fingerprint}"
            )
        self.summary.set(
            f"{details.started_at:%Y-%m-%d %H:%M:%S} | "
            f"{details.mode} | {details.dataset_display_name} | "
            f"{details.n_samples}×{details.n_features} | seed={details.seed}"
            f" | duration={details.duration_sec:.3f}s{partition_text}"
        )
        _insert_results(self.results_table, details.results)
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("end", details.log_text)
        self.log.configure(state="disabled")

    def clear_details(self, message: str) -> None:
        self.summary.set(message)
        _insert_results(self.results_table, [])
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _selection_changed(self, _event: tk.Event[Any]) -> None:
        selected = self.history_table.selection()
        if selected:
            self.on_select(selected[0])


class PyClustEvalApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PyClustEval — сравнение алгоритмов")
        self.geometry("1350x800")
        self.minsize(1050, 680)
        self.service = ComparisonService()
        self.history_service = HistoryQueryService("history")
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)
        datasets = self.service.dataset_names()
        self.local_tab = ComparisonTab(notebook, mode="local", datasets=datasets, algorithms=self.service.algorithm_names(federated=False), on_run=self.start_run)
        self.federated_tab = ComparisonTab(notebook, mode="federated", datasets=datasets, algorithms=self.service.algorithm_names(federated=True), on_run=self.start_run)
        self.history_tab = HistoryTab(notebook, on_refresh=self.refresh_history, on_select=self.load_history_details)
        notebook.add(self.local_tab, text="Локальный запуск")
        notebook.add(self.federated_tab, text="Федеративный запуск")
        notebook.add(self.history_tab, text="История")
        notebook.bind("<<NotebookTabChanged>>", self._tab_changed)
        self.after(100, self._poll_events)
        self.after(150, self.refresh_history)

    def start_run(self, request: RunRequest) -> None:
        threading.Thread(target=self._run_service, args=(request,), daemon=True).start()

    def refresh_history(self) -> None:
        self.history_tab.set_busy(True, "Чтение истории…")
        threading.Thread(target=self._load_history_list, daemon=True).start()

    def load_history_details(self, history_key: str) -> None:
        threading.Thread(target=self._load_history_details, args=(history_key,), daemon=True).start()

    def _run_service(self, request: RunRequest) -> None:
        try:
            report = self.service.compare(request, on_log=lambda text: self.events.put(("log", (request.mode, text))))
            self.events.put(("done", (request.mode, report)))
        except Exception:
            self.events.put(("error", (request.mode, traceback.format_exc())))

    def _load_history_list(self) -> None:
        try:
            self.events.put(("history_list", self.history_service.list_experiments()))
        except Exception:
            self.events.put(("history_error", traceback.format_exc()))

    def _load_history_details(self, history_key: str) -> None:
        try:
            self.events.put(("history_details", self.history_service.get_experiment(history_key)))
        except Exception:
            self.events.put(("history_error", traceback.format_exc()))

    def _tab_for_mode(self, mode: str) -> ComparisonTab:
        return self.local_tab if mode == "local" else self.federated_tab

    def _tab_changed(self, event: tk.Event[Any]) -> None:
        notebook = event.widget
        if isinstance(notebook, ttk.Notebook) and notebook.tab(notebook.select(), "text") == "История":
            self.refresh_history()

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event in {"log", "done", "error"}:
                    mode, value = payload
                    tab = self._tab_for_mode(mode)
                    if event == "log":
                        tab.append_log(value)
                    elif event == "done":
                        tab.show_results(value.results)
                        tab.append_log(f"\nСравнение завершено. История: {value.history_directory}\n")
                        tab.set_busy(False)
                        self.refresh_history()
                    else:
                        tab.append_log("\nОШИБКА:\n" + value)
                        tab.set_busy(False)
                        messagebox.showerror("Ошибка выполнения", "Тест завершился с ошибкой. Подробности находятся в логе.")
                elif event == "history_list":
                    self.history_tab.set_busy(False)
                    self.history_tab.show_summaries(payload)
                elif event == "history_details":
                    self.history_tab.show_details(payload)
                elif event == "history_error":
                    self.history_tab.set_busy(False, "Ошибка чтения истории")
                    self.history_tab.clear_details("Не удалось прочитать историю.")
                    messagebox.showerror("История", "Не удалось прочитать историю. Подробности в консоли.")
                    print(payload)
        except queue.Empty:
            pass
        self.after(100, self._poll_events)


if __name__ == "__main__":
    PyClustEvalApp().mainloop()
