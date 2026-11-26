import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from clustering_eval.application import HistoryQueryService
from clustering_eval.experiments.series_plan import resolve_document
from clustering_eval.results import archive_history


ANALYZER = Path(__file__).resolve().parents[1] / "tools" / "rebuild_validation_from_history.py"


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def report(key, date, results):
    return {"experiment_id": key, "started_at": date, "finished_at": date, "duration_sec": 0.,
            "request": {"mode": "local", "dataset_name": "iris", "seed": 17, "cluster_count_mode": "known_k"},
            "results": results, "partition": None}


def result(ari, job_id=None):
    state = {"diagnostics": {"prediction_hash": "0123", "degenerate": False}, "benchmark": {}}
    if job_id:
        state["execution"] = {"job_id": job_id}
    return {"algorithm": "kmeans", "backend": "local", "runtime_sec": 1.23, "ari": ari, "ami": None,
            "nmi": .7, "silhouette": None, "communication_bytes": None, "history": [], "model_state": state}


def bundle(root, historical):
    name = "а-серия" if not historical else "sample"
    series_name = "archive-series" if not historical else name
    if historical:
        manifest = {"format": archive_history.HISTORICAL, "series": [{"name": name, "path": series_name}]}
        scenarios = [{"scenario": "archive-baseline", "history_report": "history/comparison/report.json"}]
        save(root/series_name/"report.json", {"experiments": scenarios})
        save(root/series_name/"protocol.json", {"dataset_name": "iris"})
        item = report("old-experiment", "2026-01-05T13:00:00", [result(.25)])
    else:
        document = {
            "format": "pyclusteval.plan.v1", "campaign": {"name": "control"},
            "datasets": {"data": {"provider": "registry", "name": "iris"}},
            "scenarios": {"case-with-grid": {"mode": "local", "algorithms": ["kmeans"],
                                            "grid": {"kmeans": {"n_init": [2, 3]}}}},
            "series": [{"name": name, "dataset": "data", "seed": 17, "scenarios": ["case-with-grid"]}],
        }
        plan = resolve_document(document, base_dir=root, source_id="a"*64)
        cmp = plan["comparisons"][0]
        save(root/"reproduce"/"resolved_plan.json", plan)
        item = report(cmp["comparison_id"], "2026-01-08T10:00:00+00:00",
                      [result(ari, job["job_id"]) for ari, job in zip((.51, .83), plan["jobs"])])
        manifest = {
            "format": archive_history.GENERAL, "series": [{"name": name, "path": series_name}],
            "comparisons": [{"series": name, "scenario": cmp["scenario"],
                             "history_report": series_name + "/history/comparison/report.json"}],
        }
    folder = root / series_name / "history" / "comparison"
    save(folder/"report.json", item)
    (folder/"results.csv").write_text("algorithm,ari\nkmeans,.25\n")
    (folder/"execution.log").write_text("example", encoding="utf-8")
    save(root/"manifest.json", manifest)
    return folder


def run_analyzer(root, dest):
    ran = subprocess.run([sys.executable, "-B", str(ANALYZER), str(root), str(dest)],
                         capture_output=True, text=True, encoding="utf-8")
    assert ran.returncode == 0, ran.stderr
    return tuple(json.loads((dest / filename).read_text(encoding="utf-8"))
                 for filename in ("empirical_rows.json", "empirical_summary.json"))


def test_native_import_both_formats_and_mixed_dates(tmp_path):
    destination = tmp_path / "existing history"
    old, new = tmp_path / "historical", tmp_path / "moved archive"
    old_folder, new_folder = bundle(old, True), bundle(new, False)
    standalone = new / "merge_history.py"
    shutil.copyfile(archive_history.__file__, standalone)
    def invoke(*args):
        return subprocess.run([sys.executable, "-I", "-B", str(standalone), "--into", str(destination), *args],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    first = invoke("--archive", str(old))
    assert first.returncode == 0 and json.loads(first.stdout)["copied"] == 1
    second = invoke()
    assert second.returncode == 0 and json.loads(second.stdout)["copied"] == 1
    assert json.loads(invoke().stdout) == {"copied": 0, "skipped": 1, "conflicts": []}
    service = HistoryQueryService(destination)
    summaries = service.list_experiments()
    assert [s.result_count for s in summaries] == [2, 1]
    assert bool(summaries[0].started_at.tzinfo) and summaries[1].started_at.tzinfo is None
    for key, stored in (("а-серия_comparison", new_folder), ("sample_comparison", old_folder)):
        details = service.get_experiment(key)
        assert details.results[0].communication_bytes is None
        assert details.results[0].ari == json.loads((stored/"report.json").read_text())["results"][0]["ari"]
        assert details.results[0].ami is None and details.results[0].history == []
    collision = destination / "а-серия_comparison" / "execution.log"
    collision.write_text("existing operator log", encoding="utf-8")
    conflicts = invoke()
    assert conflicts.returncode == 3 and len(json.loads(conflicts.stdout)["conflicts"]) == 1
    assert collision.read_text() == "existing operator log"


def test_analysis_preserves_archive_scenarios_grid_and_missing_observations(tmp_path):
    for historical in (False, True):
        root = tmp_path / str(historical)
        bundle(root, historical)
        rows, summary = run_analyzer(root, tmp_path / (str(historical) + "-output"))
        name = "archive-baseline" if historical else "case-with-grid"
        assert {row["scenario"] for row in rows} == {name}
        assert summary["n_comparisons"] == 1 and summary["n_results"] == len(rows)
        assert all(r["runtime_wall_with_preprocessing"] is None for r in rows)
        assert {v["mean"] for v in summary["ari"]} == ({.25} if historical else {.51, .83})
        assert len({v["group_id"] for v in summary["ari"]}) == len(rows)
        assert summary["ami"] == []
    validated = tmp_path / "old-suite"
    save(validated/"validated_wave"/"history"/"exp"/"report.json",
         report("old", "2026-01-05T13:00:00", [result(.71)]))
    rows, summary = run_analyzer(validated, tmp_path/"validated-output")
    assert rows[0]["scenario"] == "local_known" and summary["ari"][0]["mean"] == .71
    assert summary["degenerate_counts"] == {"iris / kmeans": 0}


def test_partial_empty_archive_discovers_zero_histories(tmp_path):
    root = tmp_path / "archive"
    (root/"trial").mkdir(parents=True)
    save(root/"manifest.json", {"format": archive_history.GENERAL, "series": [{"name": "trial", "path": "trial"}],
                               "comparisons": [{"series": "trial", "scenario": "unprepared", "history_report": None}]})
    save(root/"reproduce"/"resolved_plan.json", {"comparisons": [], "jobs": []})
    assert archive_history.merge_history(root, tmp_path/"history") == {"conflicts": [], "copied": 0, "skipped": 0}
    rows, summary = run_analyzer(root, tmp_path/"output")
    assert rows == [] and summary["n_comparisons"] == summary["n_results"] == 0


def test_history_discovery_confines_all_references_to_series(tmp_path):
    root = tmp_path / "archive"
    bundle(root, True)
    save(root/"sample"/"report.json", {"experiments": [{"scenario":"case", "history_report":"../sample/history/key/report.json"}]})
    with pytest.raises(ValueError, match="Nonportable"):
        archive_history.merge_history(root, tmp_path/"history")
    assert not (tmp_path/"history").exists()
