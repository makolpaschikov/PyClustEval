"""Report host capacity and measurements from saved campaign attempts."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import platform
import shutil
import sys
from datetime import datetime, timezone


class MemoryStatus(ctypes.Structure):
    _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD),
                ("physical", ctypes.c_ulonglong), ("available", ctypes.c_ulonglong),
                ("pagefile", ctypes.c_ulonglong), ("available_pagefile", ctypes.c_ulonglong),
                ("virtual", ctypes.c_ulonglong), ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong)]


def host(directory: Path) -> dict:
    """Capture available physical memory and disk before the pilot."""
    available = total = None
    if sys.platform == "win32":
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            available, total = status.available, status.physical
    return {"recorded_at": datetime.now(timezone.utc).isoformat(),
            "platform": platform.platform(), "python": sys.version, "executable": sys.executable,
            "cpu": platform.processor(), "logical_cpus": os.cpu_count(),
            "physical_memory_bytes": total, "available_physical_bytes": available,
            "physical_memory_source": "GlobalMemoryStatusEx" if total is not None else "unavailable",
            "disk_directory": str(directory), "free_disk_bytes": shutil.disk_usage(directory).free}


def measurements(root: Path) -> dict:
    """Read a verified runner snapshot, retaining every job and attempt, including failures."""
    from clustering_eval.experiments.runner_reader import read_campaign

    saved = read_campaign(root)
    observations = []
    for entry in saved["jobs"]:
        job = entry["job"]
        accepted = entry["accepted"]
        attempts = []
        for attempt in entry["attempts"]:
            details = attempt["details"]
            observed = {"attempt_id": attempt["attempt_id"], "status": attempt["status"],
                        "reason": attempt["reason"], "worker_wall_sec": details.get("worker_wall_sec"),
                        "tree_resources": details.get("tree_resources")}
            if accepted and attempt["attempt_id"] == accepted["attempt_id"]:
                result = accepted["candidate"]
                report = result["report"]
                state = report["model_state"]
                diag = state["diagnostics"]
                observed.update(backend=report["backend"], runtime_sec=report["runtime_sec"],
                                algorithm_wall_sec=diag["runtime_algorithm_call_sec"],
                                preprocessing_sec=diag["preprocessing_sec"],
                                shared_setup_sec=state["execution"]["shared_setup_sec"],
                                worker=result["worker"],
                                infrastructure_setup_sec=state.get("flower_infrastructure_setup_sec"))
            attempts.append(observed)
        observations.append({"job_id": job["job_id"], "algorithm": job["algorithm"],
                             "requested_backend": job["backend"], "status": entry["status"],
                             "reason": entry["reason"], "attempts": attempts})
    return {"source_id": saved["source_id"], "environment": saved["environment"],
            "summary": saved["summary"], "integrity_errors": saved["integrity_errors"],
            "jobs": observations, "measurement_notes": [
                "runtime_sec uses the adapter's timing scope recorded by COMPUTE.",
                "tree_resources is absent if the runner could not record tree measurements.",
                "Worker working set covers the individual process. Windows job commit covers its tree.",
                "Sampled tree working set sums resident process pages and can count shared pages repeatedly.",
                "An absent infrastructure_setup_sec means separate Flower setup timing was unavailable.",
                "An unsuccessful attempt has no accepted model timing."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("host", "campaign"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = args.directory.resolve(strict=True)
    report = host(root) if args.action == "host" else measurements(root)
    print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))
    if report.get("integrity_errors"):
        raise SystemExit(4)


if __name__ == "__main__":
    main()
