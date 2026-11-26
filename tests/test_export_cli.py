import json
from argparse import Namespace
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

from clustering_eval.experiments.runner_state import IntegrityError
from clustering_eval.results import archive_cli


def args(path, operation, *, as_json=True):
    return Namespace(input=path, operation=operation, json=as_json)


def test_public_commands_and_bad_inputs(tmp_path, capsys, monkeypatch):
    from clustering_eval.cli import main

    for name in ("export", "verify"):
        monkeypatch.setattr(sys, "argv", ["clustereval", "series", name, str(tmp_path), "--json"])
        with pytest.raises(SystemExit) as exit_status:
            main()
        assert exit_status.value.code == 2
        report = json.loads(capsys.readouterr().out)
        assert report["result"] == "invalid_input" and report["action"] == name
        assert not report["published"] and report["complete"] is None
    process = subprocess.run([sys.executable, "-B", "-m", "clustering_eval.cli", "series", "--help"],
                             cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
    assert process.returncode == 0
    for name in ("run", "export", "verify"):
        assert name in process.stdout


def test_partial_export_and_operational_conflict_are_distinguishable(tmp_path, monkeypatch, capsys):
    outcome = {"published": True, "complete": False, "planned": 2, "totals": {"ok": 1, "timeout": 1}}
    monkeypatch.setattr(archive_cli, "publish_archive", lambda path: outcome)
    assert archive_cli.cli(args(tmp_path, "export")) == 3
    assert json.loads(capsys.readouterr().out)["result"] == "partial"
    for error, code, kind in ((archive_cli.PublicationBusy("busy"), 3, "busy"),
                              (OSError("disk failed"), 3, "operation_failed"),
                              (IntegrityError("stored label changed"), 4, "invalid")):
        def fail(path):
            raise error
        monkeypatch.setattr(archive_cli, "publish_archive", fail)
        assert archive_cli.cli(args(tmp_path, "export")) == code
        record = json.loads(capsys.readouterr().out)
        assert record["result"] == kind and not record["published"]


def test_verify_reports_current_evidence_and_leaves_archived_report_unchanged(tmp_path, monkeypatch, capsys):
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "verification.json").write_bytes(b"original")
    checked = dict(format="v1", valid=True, complete=False, planned=2, totals={"ok":1, "pending":1},
                   checks=[{"scope":"jobs", "count":2}], errors=[], not_checked=[])
    module = ModuleType("clustering_eval.results.archive_verify")
    module.verify_archive = lambda path: checked
    monkeypatch.setitem(sys.modules, module.__name__, module)
    assert archive_cli.cli(args(tmp_path, "verify")) == 3
    record = json.loads(capsys.readouterr().out)
    assert not record["published"] and record["totals"] == checked["totals"]
    checked.update(valid=False, errors=["labels.npz: SHA-256 mismatch"])
    assert archive_cli.cli(args(tmp_path, "verify", as_json=False)) == 4
    assert "labels.npz" in capsys.readouterr().err
    assert (tmp_path / "verification.json").read_bytes() == b"original"

@pytest.mark.skipif(sys.platform != "win32", reason="Uses a Windows kernel byte-range lock")
def test_transient_file_lock_keeps_published_archive_and_allows_retry(tmp_path, monkeypatch, capsys):
    import msvcrt

    from clustering_eval.cli import main
    from clustering_eval.experiments.runner_campaign import create_campaign, input_plan

    root = tmp_path / "campaign"
    source = tmp_path / "plan.json"
    source.write_text(json.dumps({
        "format": "pyclusteval.plan.v1", "campaign": {"name": "partial", "output_dir": str(root)},
        "datasets": {"iris": {"provider": "registry", "name": "iris"}},
        "scenarios": {"local": {"mode": "local", "algorithms": ["kmeans"]}},
        "series": [{"name": "iris-17", "dataset": "iris", "seed": 17, "scenarios": ["local"]}],
    }), encoding="utf-8")
    raw, plan = input_plan(source)
    create_campaign(root, source, raw, plan)
    archive = root / "archive"

    def run(name, path, expected_code, expected_result):
        monkeypatch.setattr(sys, "argv", ["clustereval", "series", name, str(path), "--json"])
        with pytest.raises(SystemExit) as result:
            main()
        report = json.loads(capsys.readouterr().out)
        assert (result.value.code, report["result"]) == (expected_code, expected_result), report.get('error', report)
        return report

    def inventory():
        return {p.relative_to(archive): p.read_bytes() for p in archive.rglob("*") if p.is_file()}

    assert run("export", root, 3, "partial")["published"]
    before = inventory()
    assert run("verify", archive, 3, "partial")["verification"]["valid"]
    with (archive / "manifest.json").open("r+b") as locked:
        msvcrt.locking(locked.fileno(), msvcrt.LK_NBLCK, 1)
        for command, path in (("verify", archive), ("export", root)):
            failure = run(command, path, 3, "operation_failed")
            assert not failure["published"] and "manifest.json" in failure["error"]
    assert inventory() == before
    assert run("verify", archive, 3, "partial")["verification"]["valid"]
    with (root / "raw" / "plan.json").open("r+b") as locked:
        msvcrt.locking(locked.fileno(), msvcrt.LK_NBLCK, 1)
        failure = run("export", root, 3, "operation_failed")
        assert not failure["published"]
    assert inventory() == before
    assert run("export", root, 3, "partial")["published"]
    (archive / "README.md").unlink()
    invalid = run("verify", archive, 4, "invalid")
    assert "README.md" in invalid["error"]
