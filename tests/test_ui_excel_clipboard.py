"""Regression checks for real Tk table copying and workbook-open workflow."""
from __future__ import annotations

import csv
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import tkinter as tk

import pytest

import pyclusteval_ui as ui
from clustering_eval.application import RunRequest, HistoryQueryService
from clustering_eval.results import HistoryStore


@pytest.fixture
def root():
    try:
        window = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"A graphical display is needed for Tk integration tests: {exc}")
    window.withdraw()
    yield window
    window.destroy()


def _table_with_rows(root):
    table = ui._create_results_table(root)
    first = table.insert("", "end", values=("Algo One", "numpy", "0.1234", 100, 2,
        "0.7543", "0.7000", "0.6900", "—", "—", "—", "0.5123", "0.2233", "aabb"))
    second = table.insert("", "end", values=("Algo Two", "numpy", "0.1235", 80, 3,
        "-0.0123", "0.5", "0.5", "—", "—", "—", "0.11", "0.01", "bbcc"))
    return table, first, second


def test_copy_all_results_has_headers_and_excel_columns(root):
    table, first, second = _table_with_rows(root)
    assert ui.copy_results_to_clipboard(table) == 2
    clipboard = root.clipboard_get()
    rows = list(csv.reader(io.StringIO(clipboard), delimiter="\t"))
    assert len(rows) == 3
    assert rows[0] == [ui.RESULT_HEADINGS[key] for key in ui.RESULT_COLUMNS]
    assert rows[1][0] == "Algo One"
    assert rows[2][5] == "-0.0123"
    assert all(len(row) == len(ui.RESULT_COLUMNS) for row in rows)


def test_ctrl_c_copies_only_selected_rows_and_ctrl_a_selects_all(root):
    table, first, second = _table_with_rows(root)
    table.selection_set(second)
    assert ui._copy_results_hotkey(SimpleNamespace(widget=table)) == "break"
    rows = list(csv.reader(io.StringIO(root.clipboard_get()), delimiter="\t"))
    assert len(rows) == 2
    assert rows[1][0] == "Algo Two"
    assert ui._select_all_results_hotkey(SimpleNamespace(widget=table)) == "break"
    assert set(table.selection()) == {first, second}
    assert ui.copy_results_to_clipboard(table, selected_only=True) == 2


def test_empty_table_is_not_copied(root):
    table = ui._create_results_table(root)
    assert ui.results_table_as_tsv(table) == ""
    assert ui.copy_results_to_clipboard(table) == 0


def test_windows_opens_exported_workbook_with_associated_app(tmp_path, monkeypatch):
    file = tmp_path / "experiment.xlsx"
    file.write_bytes(b"data")
    opened = []
    monkeypatch.setattr(ui.sys, "platform", "win32")
    monkeypatch.setattr(ui.os, "startfile", opened.append, raising=False)
    ui.open_exported_workbook(file)
    assert opened == [str(file.resolve())]


@pytest.mark.parametrize("platform,command", [("linux", "xdg-open"), ("darwin", "open")])
def test_unix_opens_without_shell_and_without_wait(tmp_path, monkeypatch, platform, command):
    file = tmp_path / "experiment.xlsx"
    file.write_bytes(b"data")
    popen = Mock()
    monkeypatch.setattr(ui.sys, "platform", platform)
    monkeypatch.setattr(ui.shutil, "which", lambda tool: "/usr/bin/" + tool)
    monkeypatch.setattr(ui.subprocess, "Popen", popen)
    ui.open_exported_workbook(file)
    args, kwargs = popen.call_args
    assert args[0] == ["/usr/bin/" + command, str(file.resolve())]
    assert kwargs["start_new_session"] is True
    assert kwargs.get("shell") is None


def test_open_nonexistent_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        ui.open_exported_workbook(tmp_path / "missing.xlsx")


def test_real_iris_export_and_copy_in_desktop(root, tmp_path, monkeypatch):
    # This is an integration test: actual comparison, XLSX creation and Tk clipboard.
    app = ui.PyClustEvalApp()
    app.withdraw()
    app.service.history_store = HistoryStore(tmp_path / "history")
    app.history_service = HistoryQueryService(tmp_path / "history")
    try:
        report = app.service.compare(RunRequest(mode="local", dataset_name="iris",
            algorithms=("kmeans", "gmm"), seed=42))
        app.local_tab.show_report(report)
        assert str(app.local_tab.copy_button.cget("state")) == "normal"
        app.local_tab.copy_button.invoke()
        rows = list(csv.reader(io.StringIO(app.clipboard_get()), delimiter="\t"))
        assert len(rows) == 3
        assert {rows[1][0], rows[2][0]} == {"kmeans", "gmm"}
        assert {row[6] for row in rows[1:]} == {
            f"{result.ami:.4f}" for result in report.results
        }, "Copying live results must include AMI"

        output = tmp_path / "real_iris.xlsx"
        monkeypatch.setattr(ui.filedialog, "asksaveasfilename", lambda **kwargs: str(output))
        opened = []
        monkeypatch.setattr(ui, "open_exported_workbook", opened.append)
        app.auto_open_excel.set(True)
        app.local_tab.export_button.invoke()
        assert output.is_file()
        assert opened == [str(output)]
        assert "передан системе" in app.local_tab.export_status.get()

        app.auto_open_excel.set(False)
        app.local_tab.export_button.invoke()
        assert opened == [str(output)]
        assert "сохранён" in app.local_tab.export_status.get()

        app.auto_open_excel.set(True)
        monkeypatch.setattr(ui, "open_exported_workbook", Mock(side_effect=OSError("no associated app")))
        warnings = []
        monkeypatch.setattr(ui.messagebox, "showwarning", lambda *args: warnings.append(args))
        app.local_tab.export_button.invoke()
        assert output.is_file(), "Failure to open must not roll back a successfully saved XLSX"
        assert len(warnings) == 1
        assert "Не удалось автоматически открыть" in warnings[0][1]

        # Archived experiment: copy the same results straight from History.
        assert report.history_directory is not None
        details = app.history_service.get_experiment(report.history_directory.name)
        app.history_tab.show_details(details)
        assert str(app.history_tab.copy_button.cget("state")) == "normal"
        app.history_tab.copy_button.invoke()
        history_rows = list(csv.reader(io.StringIO(app.clipboard_get()), delimiter="\t"))
        assert len(history_rows) == 3
        assert {history_rows[1][0], history_rows[2][0]} == {"kmeans", "gmm"}
        assert {row[6] for row in history_rows[1:]} == {
            f"{result.ami:.4f}" for result in report.results
        }, "Copying archived results must preserve AMI"
        app.history_tab.clear_details("empty")
        assert str(app.history_tab.copy_button.cget("state")) == "disabled"
    finally:
        app.destroy()
