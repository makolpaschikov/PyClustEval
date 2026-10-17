"""Desktop UI for PyClustEval.

This module contains presentation logic only. Experiment orchestration and
history access live in ``clustering_eval.application`` services.
"""

from __future__ import annotations

import queue
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

import numpy as np

from clustering_eval.application import (
    AlgorithmRunReport,
    ComparisonReport,
    ComparisonService,
    HistoryExperimentDetails,
    HistoryExperimentSummary,
    HistoryQueryService,
    PartitionReport,
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




PARTITION_MODE_VALUES = {
    "IID": "iid",
    "Dirichlet": "dirichlet",
    "Quantity skew": "quantity_skew",
    "Label-limited": "label_limited",
}

PRIVACY_MODE_VALUES = {
    "None": "none",
    "Gaussian DP": "gaussian_dp",
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
                 algorithms: list[str], on_run: Callable[[RunRequest], None],
                 on_export: Callable[[ComparisonReport], None]) -> None:
        super().__init__(master, padding=12)
        self.mode = mode
        self.on_run = on_run
        self.on_export = on_export
        self.last_report: ComparisonReport | None = None

        controls = ttk.LabelFrame(self, text="Параметры сравнения", padding=10)
        controls.pack(fill="x")

        ttk.Label(controls, text="Датасет").grid(row=0, column=0, sticky="w")
        self.dataset = ttk.Combobox(controls, values=datasets, state="readonly", width=28)
        self.dataset.grid(row=1, column=0, padx=(0, 10), pady=(3, 10), sticky="ew")

        ttk.Label(controls, text="Алгоритмы (выбери 2 или больше)").grid(
            row=0, column=1, columnspan=3, sticky="w"
        )
        algorithm_box = ttk.Frame(controls)
        algorithm_box.grid(row=1, column=1, columnspan=3, padx=(0, 10), pady=(3, 10), sticky="nsew")
        self.algorithm_list = tk.Listbox(
            algorithm_box, selectmode="extended", exportselection=False,
            height=min(max(len(algorithms), 4), 8),
        )
        for algorithm_name in algorithms:
            self.algorithm_list.insert("end", algorithm_name)
        algorithm_scroll = ttk.Scrollbar(algorithm_box, orient="vertical", command=self.algorithm_list.yview)
        self.algorithm_list.configure(yscrollcommand=algorithm_scroll.set)
        self.algorithm_list.pack(side="left", fill="both", expand=True)
        algorithm_scroll.pack(side="left", fill="y")
        algorithm_buttons = ttk.Frame(algorithm_box)
        algorithm_buttons.pack(side="left", fill="y", padx=(8, 0))
        ttk.Button(algorithm_buttons, text="Выбрать все", command=self._select_all_algorithms).pack(fill="x")
        ttk.Button(algorithm_buttons, text="Снять выбор", command=self._clear_algorithm_selection).pack(fill="x", pady=(6, 0))

        self.seed = tk.StringVar(value="42")
        self.rounds = tk.StringVar(value="10")
        self.clients = tk.StringVar(value="5")
        self.partition_mode_display = tk.StringVar(value="IID")
        self.alpha = tk.StringVar(value="0.5")
        self.participation_percent = tk.StringVar(value="100")
        self.dropout_percent = tk.StringVar(value="0")
        self.privacy_mode_display = tk.StringVar(value="None")
        self.dp_epsilon = tk.StringVar(value="5.0")
        self.dp_delta = tk.StringVar(value="1e-5")
        self.dp_clip_norm = tk.StringVar(value="1.0")

        ttk.Label(controls, text="Seed").grid(row=2, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.seed, width=12).grid(row=3, column=0, padx=(0, 10), sticky="w")
        ttk.Label(controls, text="Раунды (общий budget)").grid(row=2, column=1, sticky="w")
        ttk.Entry(controls, textvariable=self.rounds, width=12).grid(row=3, column=1, padx=(0, 10), sticky="w")

        if mode == "federated":
            ttk.Label(controls, text="Количество клиентов").grid(row=2, column=2, sticky="w")
            ttk.Spinbox(controls, from_=2, to=100, textvariable=self.clients, width=12).grid(row=3, column=2, padx=(0, 10), sticky="w")
            ttk.Label(controls, text="Разбиение").grid(row=2, column=3, sticky="w")
            self.partition_combo = ttk.Combobox(
                controls, textvariable=self.partition_mode_display,
                values=tuple(PARTITION_MODE_VALUES), state="readonly", width=18,
            )
            self.partition_combo.grid(row=3, column=3, sticky="w")
            self.partition_combo.bind("<<ComboboxSelected>>", self._partition_mode_changed)

            ttk.Label(controls, text="Dirichlet alpha").grid(row=4, column=0, sticky="w", pady=(10, 0))
            self.alpha_entry = ttk.Entry(controls, textvariable=self.alpha, width=12)
            self.alpha_entry.grid(row=5, column=0, padx=(0, 10), sticky="w")
            ttk.Label(controls, text="Participation, %").grid(row=4, column=1, sticky="w", pady=(10, 0))
            ttk.Entry(controls, textvariable=self.participation_percent, width=12).grid(
                row=5, column=1, padx=(0, 10), sticky="w"
            )
            ttk.Label(controls, text="Dropout, %").grid(row=4, column=2, sticky="w", pady=(10, 0))
            ttk.Entry(controls, textvariable=self.dropout_percent, width=12).grid(
                row=5, column=2, padx=(0, 10), sticky="w"
            )
            ttk.Label(controls, text="Privacy").grid(row=4, column=3, sticky="w", pady=(10, 0))
            self.privacy_combo = ttk.Combobox(
                controls,
                textvariable=self.privacy_mode_display,
                values=tuple(PRIVACY_MODE_VALUES),
                state="readonly",
                width=18,
            )
            self.privacy_combo.grid(row=5, column=3, sticky="w")
            self.privacy_combo.bind("<<ComboboxSelected>>", self._privacy_mode_changed)

            ttk.Label(controls, text="DP epsilon").grid(row=6, column=0, sticky="w", pady=(10, 0))
            self.dp_epsilon_entry = ttk.Entry(controls, textvariable=self.dp_epsilon, width=12)
            self.dp_epsilon_entry.grid(row=7, column=0, padx=(0, 10), sticky="w")
            ttk.Label(controls, text="DP delta").grid(row=6, column=1, sticky="w", pady=(10, 0))
            self.dp_delta_entry = ttk.Entry(controls, textvariable=self.dp_delta, width=12)
            self.dp_delta_entry.grid(row=7, column=1, padx=(0, 10), sticky="w")
            ttk.Label(controls, text="DP clip norm (raw X)").grid(row=6, column=2, sticky="w", pady=(10, 0))
            self.dp_clip_entry = ttk.Entry(controls, textvariable=self.dp_clip_norm, width=12)
            self.dp_clip_entry.grid(row=7, column=2, padx=(0, 10), sticky="w")
            fixed_text = (
                "Generic sane defaults: K=oracle • DBSCAN auto-eps(q50 k-distance)/min_samples=5 • "
                "HF_DBSCAN L=0.15/MIN_POINTS=4 • min samples/client=3 • "
                "Label-limited=2 класса/client"
            )
            ttk.Label(controls, text=fixed_text, foreground="#555555", wraplength=330).grid(
                row=6, column=3, rowspan=2, sticky="w", padx=(0, 8), pady=(8, 0)
            )
            run_row = 8
            self._partition_mode_changed()
            self._privacy_mode_changed()
        else:
            ttk.Label(
                controls,
                text=(
                    "Generic sane defaults: K=oracle • KMeans k-means++/n_init=10 • "
                    "GMM full/kmeans-init • DBSCAN auto-eps(q50 k-distance)/min_samples=5 • Agglo Ward"
                ),
                foreground="#555555",
            ).grid(row=2, column=2, columnspan=2, rowspan=2, sticky="w", pady=(0, 0))
            run_row = 4

        self.run_button = ttk.Button(controls, text="Запустить выбранные алгоритмы", command=self._submit)
        self.run_button.grid(row=run_row, column=0, columnspan=4, pady=(14, 0), sticky="ew")
        for column in range(4):
            controls.columnconfigure(column, weight=1)

        self.partition_table: ttk.Treeview | None = None
        self.participation_table: ttk.Treeview | None = None
        if mode == "federated":
            partition_box = ttk.LabelFrame(self, text="Распределение данных по клиентам", padding=8)
            partition_box.pack(fill="x", pady=(12, 0))
            columns = ("client", "samples", "classes")
            self.partition_table = ttk.Treeview(partition_box, columns=columns, show="headings", height=5)
            self.partition_table.heading("client", text="Клиент")
            self.partition_table.heading("samples", text="Объектов")
            self.partition_table.heading("classes", text="Распределение классов")
            self.partition_table.column("client", width=90, anchor="center")
            self.partition_table.column("samples", width=90, anchor="center")
            self.partition_table.column("classes", width=760, anchor="w")
            part_scroll = ttk.Scrollbar(partition_box, orient="vertical", command=self.partition_table.yview)
            self.partition_table.configure(yscrollcommand=part_scroll.set)
            self.partition_table.pack(side="left", fill="x", expand=True)
            part_scroll.pack(side="left", fill="y")

            participation_box = ttk.LabelFrame(
                self, text="Partial Participation / Dropout schedule", padding=8
            )
            participation_box.pack(fill="x", pady=(8, 0))
            ttk.Label(
                participation_box,
                text=(
                    "Итеративные алгоритмы используют расписание по раундам; "
                    "one-shot Adapted алгоритмы используют только Round 1."
                ),
                foreground="#555555",
            ).pack(anchor="w", pady=(0, 5))
            schedule_columns = ("round", "selected", "successful", "dropped")
            self.participation_table = ttk.Treeview(
                participation_box,
                columns=schedule_columns,
                show="headings",
                height=5,
            )
            for column, title, width in (
                ("round", "Раунд", 70),
                ("selected", "Выбраны", 300),
                ("successful", "Успешно", 300),
                ("dropped", "Dropout", 300),
            ):
                self.participation_table.heading(column, text=title)
                self.participation_table.column(column, width=width, anchor="center")
            schedule_scroll = ttk.Scrollbar(
                participation_box,
                orient="vertical",
                command=self.participation_table.yview,
            )
            self.participation_table.configure(yscrollcommand=schedule_scroll.set)
            self.participation_table.pack(side="left", fill="x", expand=True)
            schedule_scroll.pack(side="left", fill="y")

        results_box = ttk.LabelFrame(self, text="Результаты", padding=8)
        results_box.pack(fill="both", expand=True, pady=(12, 0))
        result_toolbar = ttk.Frame(results_box)
        result_toolbar.pack(fill="x", pady=(0, 6))
        self.export_button = ttk.Button(
            result_toolbar, text="Экспорт в Excel…", command=self._export_current, state="disabled"
        )
        self.export_button.pack(side="right")

        self.table = _create_results_table(results_box)
        scrollbar = ttk.Scrollbar(results_box, orient="horizontal", command=self.table.xview)
        self.table.configure(xscrollcommand=scrollbar.set)
        self.table.pack(fill="both", expand=True)
        scrollbar.pack(fill="x")
        ttk.Label(results_box, text="Лог").pack(anchor="w", pady=(10, 3))
        self.log = tk.Text(results_box, height=7, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True)

        if datasets:
            self.dataset.current(0)
        if algorithms:
            self.algorithm_list.selection_set(0)
            if len(algorithms) > 1:
                self.algorithm_list.selection_set(1)

    def _selected_algorithms(self) -> tuple[str, ...]:
        return tuple(str(self.algorithm_list.get(index)) for index in self.algorithm_list.curselection())

    def _select_all_algorithms(self) -> None:
        self.algorithm_list.selection_set(0, "end")

    def _clear_algorithm_selection(self) -> None:
        self.algorithm_list.selection_clear(0, "end")

    def _partition_mode_changed(self, _event: tk.Event[Any] | None = None) -> None:
        if self.mode != "federated":
            return
        is_dirichlet = PARTITION_MODE_VALUES.get(self.partition_mode_display.get()) == "dirichlet"
        self.alpha_entry.configure(state="normal" if is_dirichlet else "disabled")

    def _privacy_mode_changed(self, _event: tk.Event[Any] | None = None) -> None:
        if self.mode != "federated":
            return
        enabled = PRIVACY_MODE_VALUES.get(self.privacy_mode_display.get()) == "gaussian_dp"
        state = "normal" if enabled else "disabled"
        self.dp_epsilon_entry.configure(state=state)
        self.dp_delta_entry.configure(state=state)
        self.dp_clip_entry.configure(state=state)

    def _submit(self) -> None:
        selected_algorithms = self._selected_algorithms()
        if not self.dataset.get():
            messagebox.showerror("Ошибка", "Выбери датасет.")
            return
        if len(selected_algorithms) < 2:
            messagebox.showerror("Ошибка", "Выбери минимум два алгоритма для сравнения.")
            return
        try:
            partition_mode = PARTITION_MODE_VALUES.get(self.partition_mode_display.get(), "iid")
            federated_options: dict[str, Any] = {}
            if self.mode == "federated":
                federated_options = {
                    "participation_rate": float(self.participation_percent.get()) / 100.0,
                    "dropout_rate": float(self.dropout_percent.get()) / 100.0,
                    "privacy_mode": PRIVACY_MODE_VALUES.get(
                        self.privacy_mode_display.get(), "none"
                    ),
                    "dp_epsilon": float(self.dp_epsilon.get()),
                    "dp_delta": float(self.dp_delta.get()),
                    "dp_clip_norm": float(self.dp_clip_norm.get()),
                }
            request = RunRequest(
                mode=self.mode,  # type: ignore[arg-type]
                dataset_name=self.dataset.get(),
                algorithms=selected_algorithms,
                seed=int(self.seed.get()),
                num_clients=int(self.clients.get()),
                partition_mode=partition_mode,  # type: ignore[arg-type]
                dirichlet_alpha=float(self.alpha.get()),
                rounds=int(self.rounds.get()),
                algorithm_params_by_name={},
                **federated_options,
            )
            request.validate()
        except ValueError as error:
            messagebox.showerror("Ошибка параметров", str(error))
            return
        self.clear()
        self.set_busy(True)
        self.on_run(request)

    def _export_current(self) -> None:
        if self.last_report is not None:
            self.on_export(self.last_report)

    def set_busy(self, busy: bool) -> None:
        self.run_button.configure(
            state="disabled" if busy else "normal",
            text="Выполняется…" if busy else "Запустить выбранные алгоритмы",
        )

    def clear(self) -> None:
        self.last_report = None
        self.export_button.configure(state="disabled")
        _insert_results(self.table, [])
        self._clear_partition()
        self.set_log("")

    def _clear_partition(self) -> None:
        if self.partition_table is not None:
            for item in self.partition_table.get_children():
                self.partition_table.delete(item)
        if self.participation_table is not None:
            for item in self.participation_table.get_children():
                self.participation_table.delete(item)

    def show_partition(self, partition: PartitionReport) -> None:
        if self.partition_table is None:
            return
        self._clear_partition()
        for client_id, sample_count in enumerate(partition.client_sample_counts, start=1):
            distribution = (
                partition.client_class_counts[client_id - 1]
                if client_id - 1 < len(partition.client_class_counts) else {}
            )
            class_text = " | ".join(f"{label}: {count}" for label, count in distribution.items()) or "—"
            self.partition_table.insert("", "end", values=(f"Client {client_id}", sample_count, class_text))
        if self.participation_table is not None:
            for entry in partition.round_schedule:
                selected = ", ".join(str(int(value) + 1) for value in entry.get("selected_clients", [])) or "—"
                successful = ", ".join(str(int(value) + 1) for value in entry.get("successful_clients", [])) or "—"
                dropped = ", ".join(str(int(value) + 1) for value in entry.get("dropped_clients", [])) or "—"
                self.participation_table.insert(
                    "",
                    "end",
                    values=(entry.get("round", "—"), selected, successful, dropped),
                )

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

    def show_report(self, report: ComparisonReport) -> None:
        self.last_report = report
        _insert_results(self.table, report.results)
        if report.partition is not None:
            self.show_partition(report.partition)
        self.export_button.configure(state="normal")


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
            ("algorithms", "Алгоритмы", 420), ("duration", "Время, сек", 90),
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
                ", ".join(summary.algorithms),
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
                f" | participation={details.partition.participation_rate:.0%}"
                f" | dropout={details.partition.dropout_rate:.0%}"
            )
        privacy_text = ""
        if details.results:
            benchmark = dict(details.results[0].model_state.get("benchmark") or {})
            privacy_mode = str(benchmark.get("privacy_mode", "none"))
            if privacy_mode == "gaussian_dp":
                privacy_text = (
                    f" | Gaussian DP ε={benchmark.get('dp_epsilon')}"
                    f", δ={benchmark.get('dp_delta')}"
                )
        self.summary.set(
            f"{details.started_at:%Y-%m-%d %H:%M:%S} | "
            f"{details.mode} | {details.dataset_display_name} | "
            f"{details.n_samples}×{details.n_features} | seed={details.seed}"
            f" | duration={details.duration_sec:.3f}s{partition_text}{privacy_text}"
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
        self.geometry("1400x1000")
        self.minsize(1100, 820)
        self.service = ComparisonService()
        self.history_service = HistoryQueryService("history")
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)
        datasets = self.service.dataset_names()
        self.local_tab = ComparisonTab(notebook, mode="local", datasets=datasets, algorithms=self.service.algorithm_names(federated=False), on_run=self.start_run, on_export=self.export_report)
        self.federated_tab = ComparisonTab(notebook, mode="federated", datasets=datasets, algorithms=self.service.algorithm_names(federated=True), on_run=self.start_run, on_export=self.export_report)
        self.history_tab = HistoryTab(notebook, on_refresh=self.refresh_history, on_select=self.load_history_details)
        notebook.add(self.local_tab, text="Локальный запуск")
        notebook.add(self.federated_tab, text="Федеративный запуск")
        notebook.add(self.history_tab, text="История")
        notebook.bind("<<NotebookTabChanged>>", self._tab_changed)
        self.after(100, self._poll_events)
        self.after(150, self.refresh_history)

    def start_run(self, request: RunRequest) -> None:
        threading.Thread(target=self._run_service, args=(request,), daemon=True).start()

    def export_report(self, report: ComparisonReport) -> None:
        default_name = f"{report.request.dataset_name}_{report.request.mode}_{report.started_at:%Y%m%d_%H%M%S}.xlsx"
        path = filedialog.asksaveasfilename(
            title="Экспорт сравнения в Excel",
            defaultextension=".xlsx",
            initialfile=default_name,
            filetypes=(("Excel workbook", "*.xlsx"),),
        )
        if not path:
            return
        try:
            saved = self.service.export_excel(report, path)
        except Exception as error:
            messagebox.showerror("Экспорт в Excel", f"Не удалось создать файл:\n{error}")
            return
        messagebox.showinfo("Экспорт в Excel", f"Отчёт сохранён:\n{saved}")

    def refresh_history(self) -> None:
        self.history_tab.set_busy(True, "Чтение истории…")
        threading.Thread(target=self._load_history_list, daemon=True).start()

    def load_history_details(self, history_key: str) -> None:
        threading.Thread(target=self._load_history_details, args=(history_key,), daemon=True).start()

    def _run_service(self, request: RunRequest) -> None:
        try:
            report = self.service.compare(
                request,
                on_log=lambda text: self.events.put(("log", (request.mode, text))),
                on_partition=lambda partition: self.events.put(("partition", (request.mode, partition))),
            )
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
                if event in {"log", "partition", "done", "error"}:
                    mode, value = payload
                    tab = self._tab_for_mode(mode)
                    if event == "log":
                        tab.append_log(value)
                    elif event == "partition":
                        tab.show_partition(value)
                    elif event == "done":
                        tab.show_report(value)
                        tab.append_log(f"\nСравнение завершено. История: {value.history_directory}\n")
                        tab.set_busy(False)
                        self.refresh_history()
                    else:
                        tab.append_log("\nОШИБКА:\n" + value)
                        tab.set_busy(False)
                        lines = [line.strip() for line in str(value).splitlines() if line.strip()]
                        reason = lines[-1] if lines else "Неизвестная ошибка"
                        messagebox.showerror(
                            "Ошибка выполнения",
                            "Тест завершился с ошибкой:\n\n" + reason + "\n\nПолный traceback находится в логе.",
                        )
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
