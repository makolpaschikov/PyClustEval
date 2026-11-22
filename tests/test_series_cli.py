from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def series(*args: str | Path):
    return subprocess.run([sys.executable, "-B", "-m", "clustering_eval.cli", "series", *map(str, args)],
                          cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True, timeout=90)


def test_cli_plan_publication_and_error_preserve_prior_output(tmp_path):
    pilot = Path(__file__).resolve().parents[1] / "configs/series/pilot.yaml"
    result = series("validate", pilot, "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["counts"] == {"series": 2, "comparisons": 6, "jobs": 12}
    output = tmp_path / "resolved plan.json"
    result = series("plan", pilot, "--output", output, "--json")
    assert result.returncode == 0, result.stderr
    previous = output.read_bytes()
    assert json.loads(previous)["counts"]["jobs"] == 12
    broken = tmp_path / "invalid.yaml"
    broken.write_text("format: pyclusteval.plan.v1\ncampaign: {}\ncampaign: {}\n", encoding="utf-8")
    failed = series("plan", broken, "--output", output)
    assert failed.returncode == 2 and "duplicate" in failed.stderr
    assert output.read_bytes() == previous


def test_migrate_preserves_legacy_protocol_and_refuses_input_overwrite(tmp_path):
    src = tmp_path / "old config.json"
    old = {"datasets": [{"name": "iris"}], "algorithms": [{"name": "kmeans"}],
           "metrics": ["ari"], "partitioning": {"clients": [3], "modes": ["iid"]}}
    original = json.dumps(old)
    src.write_text(original, encoding="utf-8")
    assert series("migrate", src, "--output", src).returncode == 2
    assert src.read_text(encoding="utf-8") == original
    out = tmp_path / "imported.json"
    convert = series("migrate", src, "--output", out)
    assert convert.returncode == 0, convert.stderr
    result = series("plan", out, "--json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    protocol = data["comparisons"][0]["protocol"]
    assert (protocol["mode"], protocol["num_clients"], protocol["metrics"]) == ("local", 3, ["ari"])
    job, = data["jobs"]
    assert job["effective_params"]["rounds"] == 10
    assert job["effective_params"]["k"] == 3 and job["algorithm"] == "kmeans"
    published = out.read_bytes()
    old["partitioning"] = {"clients": [1], "modes": ["label_limited"]}
    src.write_text(json.dumps(old), encoding="utf-8")
    refused = series("migrate", src, "--output", out)
    assert refused.returncode == 2 and "cannot cover 3 classes" in refused.stderr
    assert out.read_bytes() == published


def test_resolved_archive_paths_are_relative_to_published_document(tmp_path, monkeypatch):
    from argparse import Namespace
    from clustering_eval.cli import _series
    from clustering_eval.experiments import series_plan

    archive = tmp_path / "study" / "experiments"
    data = archive / "datasets" / "iris.npz"
    data.parent.mkdir(parents=True)
    data.write_bytes(b"fixture marker")
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    src = plan_dir / "historical.json"
    src.write_text(json.dumps({"historical": {"path": "../study/experiments"}}), encoding="utf-8")
    output = tmp_path / "exports" / "nested" / "resolved.json"
    def resolve(document, *, base_dir, source_id):
        assert (base_dir/document["historical"]["path"]).resolve() == archive
        return {"historical": document["historical"], "datasets": [{"path": "datasets/iris.npz"}],
                "execution_readiness": {"status": "not_checked"},
                "jobs": [{"backend": "local", "job_id": "unchanged"}],
                "counts": {"jobs": 1, "series": 1, "comparisons": 1}}
    monkeypatch.setattr(series_plan, "checkout_source_id", lambda: "a" * 64)
    monkeypatch.setattr(series_plan, "resolve_document", resolve)
    _series(Namespace(input=src, operation="plan", output=output, json=True))
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert (output.parent / saved["historical"]["path"] / saved["datasets"][0]["path"]).samefile(data)
    assert saved["jobs"][0]["job_id"] == "unchanged"


def test_validate_reports_unchecked_flower_lifecycle(tmp_path):
    source = tmp_path / "warm.json"
    source.write_text(json.dumps({"format": "pyclusteval.plan.v1", "campaign": {"name": "warm"},
        "datasets": {"iris": {"provider": "registry", "name": "iris"}},
        "series": [{"name": "s", "dataset": "iris", "scenarios": ["f"], "seed": 42}],
        "execution": {"profile": "warm"},
        "scenarios": {"f": {"mode": "federated", "stopping_profile": "current_gui",
                           "algorithms": ["fed_kmeans_flower"]}}}), encoding="utf-8")
    result = series("validate", source, "--json")
    assert result.returncode == 0, result.stderr
    readiness = json.loads(result.stdout)["execution_readiness"]
    assert readiness == {"status": "not_checked", "scope": "backend_and_lifecycle",
                         "profiles": [{"backend": "flower-simulation", "lifecycle": "warm"}]}
