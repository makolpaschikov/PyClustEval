"""Behavioral checks for native Windows campaign worker ownership."""

from __future__ import annotations

from contextlib import contextmanager, ExitStack
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from clustering_eval.experiments.runner_process import (
    CampaignBusy, campaign_lock, check_resources, is_campaign_active, run_owned, worker_env,
)

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object tests")
CHECKOUT = Path(__file__).resolve().parents[1]
CHILD = """
import os, pathlib, sys, time
folder = pathlib.Path(sys.argv[1])
with (folder / "child.writes").open("wb", buffering=0) as probe:
    probe.write(b".")
    (folder / "child.pid").write_text(str(os.getpid()))
    end = time.monotonic() + 12
    while time.monotonic() < end:
        probe.write(b".")
        time.sleep(.002)
"""
TREE = """
import os, pathlib, subprocess, sys, time
folder = pathlib.Path(sys.argv[1])
child = subprocess.Popen([sys.executable, "-c", CHILD_CODE, str(folder)])
while not (folder / "child.pid").exists():
    time.sleep(.01)
(folder / "worker.pid").write_text(str(os.getpid()))
print("spawned", flush=True)
if sys.argv[2] == "exception":
    raise RuntimeError("fixture failure")
if sys.argv[2] == "linger":
    time.sleep(12)
""".replace("CHILD_CODE", repr(CHILD))


def _run(folder: Path, code: str, *args: str, timeout: float = 7.0, deadline=None,
         memory_limit=None, on_stop=None):
    return run_owned(
        [sys.executable, "-B", "-c", code, *args], cwd=CHECKOUT, env=worker_env(2),
        stdout_path=folder / "stdout.log", stderr_path=folder / "stderr.log",
        timeout_sec=timeout, deadline_utc=deadline, memory_limit_mb=memory_limit, on_stop=on_stop,
    )


def _read_pid(path: Path) -> int:
    end = time.monotonic() + 6
    while time.monotonic() < end:
        try:
            value = path.read_text()
            if value:
                return int(value)
        except FileNotFoundError:
            pass
        time.sleep(.01)
    pytest.fail(f"Process did not reach ready marker: {path}")


@contextmanager
def _process_handle(pid: int, *, terminate: bool = False):
    import _winapi

    access = 0x00100000 | (0x0001 if terminate else 0)  # SYNCHRONIZE [+ PROCESS_TERMINATE]
    handle = _winapi.OpenProcess(access, False, pid)
    try:
        yield handle
    finally:
        _winapi.CloseHandle(handle)


def _has_exited(pid: int) -> bool:
    import _winapi

    try:
        with _process_handle(pid) as handle:
            return _winapi.WaitForSingleObject(handle, 0) == _winapi.WAIT_OBJECT_0
    except OSError as error:
        if error.winerror == 87:  # no such process
            return True
        raise


@contextmanager
def _acquire_after_crash(root: Path):
    end = time.monotonic() + 5
    with ExitStack() as owner:
        while True:
            try:
                owner.enter_context(campaign_lock(root))
                break
            except CampaignBusy:
                if time.monotonic() >= end:
                    raise
                time.sleep(0)
        yield


@pytest.mark.parametrize(("mode", "code"), [("finish", 0), ("exception", 1)])
def test_worker_exit_drains_descendants_and_retains_logs(tmp_path, mode, code):
    with campaign_lock(tmp_path):
        result = _run(tmp_path, TREE, str(tmp_path), mode)
    assert (result.reason, result.returncode) == ("exited", code)
    assert _has_exited(_read_pid(tmp_path / "child.pid"))
    assert "spawned" in (tmp_path / "stdout.log").read_text()
    assert ("fixture failure" in (tmp_path / "stderr.log").read_text()) == (mode == "exception")


def test_blas_settings_are_present_before_import(tmp_path):
    code = """
import os, sys, json
before = "numpy" in sys.modules
print(json.dumps([before, [os.environ[name] for name in
    ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")]]))
import numpy
from threadpoolctl import threadpool_info
numpy.dot([2.], [3.])
print(json.dumps([p["num_threads"] for p in threadpool_info() if p["user_api"] == "blas"]))
"""
    result = _run(tmp_path, code)
    assert result.returncode == 0, (tmp_path / "stderr.log").read_text()
    initial, pools = map(json.loads, (tmp_path / "stdout.log").read_text().splitlines())
    assert initial == [False, ["2", "2", "2"]]
    assert pools and all(value == 2 for value in pools)


@pytest.mark.parametrize("stop", ["timeout", "total_time", "cancelled", "callback_exception"])
def test_stop_affects_only_this_tree(tmp_path, stop):
    import _thread

    outside = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"],
                               stdin=subprocess.PIPE)
    outcome = []
    def on_stop(reason):
        outcome.append(reason)
        if stop == "callback_exception":
            raise RuntimeError("journal fixture error")

    # The synthetic interrupt reaches the same KeyboardInterrupt branch as console Ctrl+C.
    interrupter = None
    if stop == "cancelled":
        def interrupt_when_ready():
            _read_pid(tmp_path / "worker.pid")
            _thread.interrupt_main()
        interrupter = threading.Thread(target=interrupt_when_ready)
        interrupter.start()
    try:
        with campaign_lock(tmp_path):
            kwargs = dict(
                timeout=1.5 if stop in {"timeout", "callback_exception"} else 6,
                deadline=time.time() + 1.5 if stop == "total_time" else None, on_stop=on_stop,
            )
            if stop == "callback_exception":
                with pytest.raises(RuntimeError, match="journal fixture"):
                    _run(tmp_path, TREE, str(tmp_path), "linger", **kwargs)
            else:
                result = _run(tmp_path, TREE, str(tmp_path), "linger", **kwargs)
                assert result.reason == stop
        assert outcome == ["timeout" if stop == "callback_exception" else stop]
        assert _has_exited(_read_pid(tmp_path / "worker.pid"))
        assert _has_exited(_read_pid(tmp_path / "child.pid"))
        assert outside.poll() is None
    finally:
        if interrupter is not None:
            interrupter.join(7)
        outside.stdin.close()
        outside.wait(timeout=5)


def test_hard_kill_then_immediate_owner_recovery(tmp_path):
    import _winapi

    folder = tmp_path / "owned output"
    folder.mkdir()
    uncreated = folder / "campaign directory"
    assert not is_campaign_active(uncreated)
    supervisor_code = """
import os, sys
from pathlib import Path
from clustering_eval.experiments.runner_process import campaign_lock, run_owned, worker_env
folder = Path(sys.argv[1])
with campaign_lock(folder / "campaign directory"):
    (folder / "supervisor.pid").write_text(str(os.getpid()))
    run_owned([sys.executable,"-B","-c",sys.argv[2],str(folder),"linger"], cwd=Path.cwd(),
              env=worker_env(1), stdout_path=folder/"stdout.log", stderr_path=folder/"stderr.log",
              timeout_sec=10, deadline_utc=None, memory_limit_mb=None)
"""
    with subprocess.Popen([sys.executable, "-B", "-c", supervisor_code, str(folder), TREE],
                          cwd=CHECKOUT) as launcher, ExitStack() as handles:
        owner = handles.enter_context(_process_handle(_read_pid(folder / "supervisor.pid"), terminate=True))
        members = [handles.enter_context(_process_handle(_read_pid(folder / name)))
                   for name in ("worker.pid", "child.pid")]
        assert is_campaign_active(uncreated)
        with pytest.raises(CampaignBusy), campaign_lock(uncreated):
            pytest.fail("second owner admitted")
        _winapi.TerminateProcess(owner, 9)
        # Reacquire immediately without waiting for the old worker or supervisor.
        with _acquire_after_crash(uncreated):
            size_on_acquisition = (folder / "child.writes").stat().st_size
            assert all(_winapi.WaitForSingleObject(h, 0) == _winapi.WAIT_OBJECT_0 for h in members)
            assert (folder / "child.writes").stat().st_size == size_on_acquisition
        assert launcher.wait(timeout=5) != 0
    assert not is_campaign_active(uncreated)
    assert not uncreated.exists()


def test_hard_job_commit_limit_is_shared_by_descendants(tmp_path):
    check_resources(96)
    allocation = """
try:
    chunk = bytearray(50 * 1024**2)
    print("allocated")
except MemoryError:
    print("limited")
"""
    solo = tmp_path / "single"
    solo.mkdir()
    assert _run(solo, allocation, memory_limit=96).returncode == 0
    assert (solo / "stdout.log").read_text().strip() == "allocated"
    parent = """
import subprocess, sys
chunk = bytearray(50 * 1024**2)
subprocess.run([sys.executable, "-c", sys.argv[1]], check=True)
"""
    assert _run(tmp_path, parent, allocation, memory_limit=96).returncode == 0
    assert (tmp_path / "stdout.log").read_text().strip() == "limited"


def test_owner_dies_as_native_create_returns(tmp_path):
    # Kill the test supervisor before any post-creation user-mode code can assign
    # the child, inspect it or register cleanup for the returned process handle.
    supervisor = """
import os, sys
from pathlib import Path
from clustering_eval.experiments import runner_windows as win
from clustering_eval.experiments.runner_process import campaign_lock, run_owned, worker_env
folder = Path(sys.argv[1])
original = win._create_process
def die_after_creation(*args):
    if original(*args):
        (folder / "worker.pid").write_text(str(args[-1]._obj.process_id))
        os._exit(71)
    return False
win._create_process = die_after_creation
with campaign_lock(folder):
    run_owned([sys.executable, "-c", "import time; time.sleep(12)"], cwd=Path.cwd(),
              env=worker_env(1), stdout_path=folder/"stdout.log", stderr_path=folder/"stderr.log",
              timeout_sec=5, deadline_utc=None, memory_limit_mb=None)
"""
    owner = subprocess.run([sys.executable, "-B", "-c", supervisor, str(tmp_path)],
                           cwd=CHECKOUT, timeout=7)
    assert owner.returncode == 71
    with _acquire_after_crash(tmp_path):
        assert _has_exited(_read_pid(tmp_path / "worker.pid"))


def test_expired_calendar_deadline_does_not_launch_worker(tmp_path):
    marker = tmp_path / "started"
    result = _run(tmp_path, "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()", str(marker),
                  deadline=time.time() - 1)
    assert result.reason == "total_time" and result.returncode is None
    assert not marker.exists()


def test_failed_launch_releases_observer_and_log_handles(tmp_path):
    out = tmp_path / "stdout.log"
    err = tmp_path / "stderr.log"
    with campaign_lock(tmp_path):
        with pytest.raises(FileNotFoundError):
            run_owned([str(tmp_path / "missing-program.exe")], cwd=CHECKOUT, env=worker_env(1),
                      stdout_path=out, stderr_path=err, timeout_sec=2, deadline_utc=None,
                      memory_limit_mb=None)
    assert not is_campaign_active(tmp_path)
    out.rename(tmp_path / "retained.stdout")
    err.rename(tmp_path / "retained.stderr")


@pytest.mark.parametrize("exists_before_lock", [False, True])
def test_drive_aliases_share_campaign_owner(tmp_path, exists_before_lock):
    root = tmp_path / "Case of campaign"
    extended = Path("\\\\?\\" + str(root))
    direct_alias = tmp_path / ".." / tmp_path.name / "CASE OF CAMPAIGN"
    if exists_before_lock:
        root.mkdir()
    with campaign_lock(extended):
        for alias in (root, direct_alias, root.with_name(root.name + ". ")):
            assert is_campaign_active(alias)
            with pytest.raises(CampaignBusy), campaign_lock(alias):
                pytest.fail("another owner entered through a drive path alias")
        root.mkdir(exist_ok=True)
        assert is_campaign_active(root)
    with campaign_lock(root):
        assert is_campaign_active(extended)
    assert not is_campaign_active(extended)


def test_extended_unc_spelling_shares_campaign_owner(monkeypatch):
    # Supply normalized UNC names directly, without requiring an SMB share.
    monkeypatch.setattr(Path, "resolve", lambda self: self)
    ordinary = Path(r"\\server\StudyShare\future campaign")
    extended = Path(r"\\?\UNC\SERVER\studyshare\future campaign")
    with campaign_lock(ordinary):
        assert is_campaign_active(extended)
        with pytest.raises(CampaignBusy), campaign_lock(extended):
            pytest.fail("another owner entered through the extended UNC spelling")
