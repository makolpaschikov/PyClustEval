"""Win32 job, process and namespace primitives for the local campaign runner."""

from __future__ import annotations

import ctypes as ct
from ctypes import wintypes as wt
from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import asdict, dataclass
import msvcrt
import os
from pathlib import Path
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
import _winapi

_kernel = ct.WinDLL("kernel32", use_last_error=True)
_pointer = ct.c_void_p


def _api(name, result, *arguments):
    function = getattr(_kernel, name)
    function.argtypes = arguments
    function.restype = result
    return function


def _check(value):
    if not value:
        raise ct.WinError(ct.get_last_error())
    return value


class _BasicLimits(ct.Structure):
    _fields_ = [
        ("per_process_time", ct.c_int64), ("per_job_time", ct.c_int64),
        ("flags", wt.DWORD), ("min_working_set", ct.c_size_t),
        ("max_working_set", ct.c_size_t), ("active_process_limit", wt.DWORD),
        ("affinity", ct.c_size_t), ("priority_class", wt.DWORD),
        ("scheduling_class", wt.DWORD),
    ]


class _ExtendedLimits(ct.Structure):
    _fields_ = [
        ("basic", _BasicLimits), ("io_counters", ct.c_uint64 * 6),
        ("process_memory", ct.c_size_t), ("job_memory", ct.c_size_t),
        ("peak_process_memory", ct.c_size_t), ("peak_job_memory", ct.c_size_t),
    ]


class _Accounting(ct.Structure):
    _fields_ = [
        ("times", ct.c_int64 * 4), ("page_faults", wt.DWORD),
        ("total_processes", wt.DWORD), ("active_processes", wt.DWORD),
        ("terminated_processes", wt.DWORD),
    ]


class _ProcessMemory(ct.Structure):
    _fields_ = [("size", wt.DWORD), ("page_faults", wt.DWORD),
                ("peak_working_set", ct.c_size_t), ("working_set", ct.c_size_t),
                ("pool_and_pagefile_counters", ct.c_size_t * 6)]


class _MemoryStatus(ct.Structure):
    _fields_ = [("size", wt.DWORD), ("load", wt.DWORD),
                ("total_physical", ct.c_uint64), ("available_physical", ct.c_uint64),
                ("pagefile_and_virtual", ct.c_uint64 * 5)]


class _StartupInfo(ct.Structure):
    _fields_ = [
        ("cb", wt.DWORD), ("reserved", wt.LPWSTR), ("desktop", wt.LPWSTR),
        ("title", wt.LPWSTR), ("dimensions", wt.DWORD * 6), ("fill", wt.DWORD),
        ("flags", wt.DWORD), ("show", wt.WORD), ("cb_reserved", wt.WORD),
        ("reserved2", _pointer), ("stdin", wt.HANDLE), ("stdout", wt.HANDLE),
        ("stderr", wt.HANDLE),
    ]


class _StartupInfoEx(ct.Structure):
    _fields_ = [("startup", _StartupInfo), ("attributes", _pointer)]


class _ProcessInfo(ct.Structure):
    _fields_ = [
        ("process", wt.HANDLE), ("thread", wt.HANDLE),
        ("process_id", wt.DWORD), ("thread_id", wt.DWORD),
    ]


_create_mutex = _api("CreateMutexW", wt.HANDLE, _pointer, wt.BOOL, wt.LPCWSTR)
_open_mutex = _api("OpenMutexW", wt.HANDLE, wt.DWORD, wt.BOOL, wt.LPCWSTR)
_create_event = _api("CreateEventW", wt.HANDLE, _pointer, wt.BOOL, wt.BOOL, wt.LPCWSTR)
_set_event = _api("SetEvent", wt.BOOL, wt.HANDLE)
_create_job = _api("CreateJobObjectW", wt.HANDLE, _pointer, wt.LPCWSTR)
_open_job = _api("OpenJobObjectW", wt.HANDLE, wt.DWORD, wt.BOOL, wt.LPCWSTR)
_limit_job = _api("SetInformationJobObject", wt.BOOL, wt.HANDLE, ct.c_int, _pointer, wt.DWORD)
_query_job = _api("QueryInformationJobObject", wt.BOOL, wt.HANDLE, ct.c_int, _pointer, wt.DWORD, _pointer)
_terminate_job = _api("TerminateJobObject", wt.BOOL, wt.HANDLE, wt.UINT)
_is_member = _api("IsProcessInJob", wt.BOOL, wt.HANDLE, wt.HANDLE, ct.POINTER(wt.BOOL))
_memory_info = _api("K32GetProcessMemoryInfo", wt.BOOL, wt.HANDLE, ct.POINTER(_ProcessMemory), wt.DWORD)
_memory_status = _api("GlobalMemoryStatusEx", wt.BOOL, ct.POINTER(_MemoryStatus))
_init_attrs = _api("InitializeProcThreadAttributeList", wt.BOOL, _pointer, wt.DWORD, wt.DWORD,
                   ct.POINTER(ct.c_size_t))
_set_attr = _api("UpdateProcThreadAttribute", wt.BOOL, _pointer, wt.DWORD, ct.c_size_t, _pointer,
                 ct.c_size_t, _pointer, _pointer)
_delete_attrs = _api("DeleteProcThreadAttributeList", None, _pointer)
_create_process = _api("CreateProcessW", wt.BOOL, wt.LPCWSTR, wt.LPWSTR, _pointer, _pointer,
                       wt.BOOL, wt.DWORD, _pointer, wt.LPCWSTR, ct.POINTER(_StartupInfoEx),
                       ct.POINTER(_ProcessInfo))

_ERROR_ALREADY_EXISTS = 183
_ERROR_FILE_NOT_FOUND = 2
_JOB_SET_QUERY_TERMINATE = 0x0002 | 0x0004 | 0x0008


@contextmanager
def exclusive_name(name: str) -> Iterator[int | None]:
    """Keep the namespace entry alive only for the owner's handle lifetime."""
    ct.set_last_error(0)
    handle = _check(_create_mutex(None, False, name))
    try:
        yield None if ct.get_last_error() == _ERROR_ALREADY_EXISTS else handle
    finally:
        _winapi.CloseHandle(handle)


def owner_exists(name: str) -> bool:
    handle = _open_mutex(0x00100000, False, name)  # SYNCHRONIZE
    if not handle and ct.get_last_error() == _ERROR_FILE_NOT_FOUND:
        return False
    _winapi.CloseHandle(_check(handle))
    return True


def _accounting(job: int) -> _Accounting:
    info = _Accounting()
    _check(_query_job(job, 1, ct.byref(info), ct.sizeof(info), None))
    return info


def available_physical_memory() -> int | None:
    status = _MemoryStatus()
    status.size = ct.sizeof(status)
    return status.available_physical if _memory_status(ct.byref(status)) else None


def _process_memory(handle: int) -> _ProcessMemory:
    memory = _ProcessMemory()
    memory.size = ct.sizeof(memory)
    _check(_memory_info(handle, ct.byref(memory), memory.size))
    return memory


def worker_peak_working_set() -> int:
    return _process_memory(_winapi.GetCurrentProcess()).peak_working_set


def _member_pids(job: int, capacity: int) -> list[int]:
    # JobObjectBasicProcessIdList starts with two DWORD counts and a ULONG_PTR array.
    class Members(ct.Structure):
        _fields_ = [("assigned", wt.DWORD), ("returned", wt.DWORD),
                    ("pids", ct.c_size_t * capacity)]

    members = Members()
    success = _query_job(job, 3, ct.byref(members), ct.sizeof(members), None)
    if not success and ct.get_last_error() == 234:  # ERROR_MORE_DATA
        return _member_pids(job, max(capacity * 2, members.assigned))
    _check(success)
    return list(members.pids[:members.returned])


@dataclass
class TreeResources:
    """Kernel commit high-water and sampled sums of current member working sets.

    A working-set sample enumerates members once and reads each by stable handle.
    Shared pages can count in more than one process. An unreadable or disappearing
    member invalidates the sample. Short-lived peaks can fall between samples.
    """

    working_set_sample_interval_sec: float = 0.25
    working_set_samples: int = 0
    working_set_incomplete_samples: int = 0
    max_sampled_working_set_bytes: int | None = None
    peak_commit_bytes: int | None = None
    memory_limit_bytes: int | None = None
    total_processes: int | None = None
    active_processes_after_cleanup: int | None = None

    def sample(self, job: int) -> None:
        total = 0
        try:
            pids = _member_pids(job, 16)
            for pid in pids:
                proc = _winapi.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
                try:
                    member = wt.BOOL()
                    _check(_is_member(proc, job, ct.byref(member)))
                    if not member.value:
                        self.working_set_incomplete_samples += 1
                        return
                    total += _process_memory(proc).working_set
                finally:
                    _winapi.CloseHandle(proc)
        except OSError:
            self.working_set_incomplete_samples += 1
            return
        if pids:
            self.working_set_samples += 1
            self.max_sampled_working_set_bytes = max(self.max_sampled_working_set_bytes or 0, total)

    def after_drain(self, job: int) -> None:
        limits = _ExtendedLimits()
        _check(_query_job(job, 9, ct.byref(limits), ct.sizeof(limits), None))
        accounting = _accounting(job)
        self.peak_commit_bytes = limits.peak_job_memory
        if limits.basic.flags & 0x00000200:
            self.memory_limit_bytes = limits.job_memory
        self.total_processes = accounting.total_processes
        self.active_processes_after_cleanup = accounting.active_processes

    def record(self) -> dict:
        record = {**asdict(self), "scope": "Windows job object and member processes",
                  "commit_source": "QueryInformationJobObject / PeakJobMemoryUsed",
                  "working_set_source": "sum of GetProcessMemoryInfo / WorkingSetSize; shared pages can repeat"}
        if self.max_sampled_working_set_bytes is None:
            record["working_set_unavailable_reason"] = "No complete sample of live job members"
        return record


def stop_and_drain(job: int) -> None:
    """Drain all members, including children left behind by a successful worker."""
    if not _accounting(job).active_processes:
        return
    # Stop admitting descendants before taking stable process handles. The job's
    # active count can reach zero before the terminated process objects signal.
    limits = _ExtendedLimits()
    _check(_query_job(job, 9, ct.byref(limits), ct.sizeof(limits), None))
    limits.basic.flags |= 0x00000008  # JOB_OBJECT_LIMIT_ACTIVE_PROCESS
    limits.basic.active_process_limit = 0
    _check(_limit_job(job, 9, ct.byref(limits), ct.sizeof(limits)))
    with ExitStack() as cleanup:
        handles = []
        for pid in _member_pids(job, max(_accounting(job).active_processes, 1)):
            try:
                proc = _winapi.OpenProcess(0x00101000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED
            except OSError as error:
                if error.winerror == 87:  # process exited between enumeration and opening
                    continue
                raise
            cleanup.callback(_winapi.CloseHandle, proc)
            member = wt.BOOL()
            _check(_is_member(proc, job, ct.byref(member)))
            if member.value:
                handles.append(proc)
        _check(_terminate_job(job, 1))
        for proc in handles:
            _winapi.WaitForSingleObject(proc, _winapi.INFINITE)
        while _accounting(job).active_processes:
            time.sleep(0.01)


def recover_job(name: str) -> None:
    handle = _open_job(_JOB_SET_QUERY_TERMINATE, False, name)
    if not handle and ct.get_last_error() == _ERROR_FILE_NOT_FOUND:
        return
    _check(handle)
    try:
        stop_and_drain(handle)
    finally:
        _winapi.CloseHandle(handle)


@contextmanager
def _recovery_guard(job: int, lease: int) -> Iterator[None]:
    """Keep the campaign leased until a surviving observer has verified rundown.

    On abrupt owner death, Windows can release the owner's namespace handles
    before the worker process objects signal. The observer retains its own lease
    and job references and wakes on the actual supervisor process handle.
    """
    current = _winapi.GetCurrentProcess()
    with ExitStack() as events:
        ready = _check(_create_event(None, True, False, None))
        events.callback(_winapi.CloseHandle, ready)
        done = _check(_create_event(None, True, False, None))
        events.callback(_winapi.CloseHandle, done)
        with ExitStack() as inherit:
            handles = []
            for source, access in ((job, _JOB_SET_QUERY_TERMINATE), (lease, 0x00100000),
                                   (current, 0x00100000), (ready, 0x0002), (done, 0x00100000)):
                handle = _winapi.DuplicateHandle(current, source, current, access, True, 0)
                handles.append(handle)
                inherit.callback(_winapi.CloseHandle, handle)
            startup = subprocess.STARTUPINFO(lpAttributeList={"handle_list": handles})
            guard = subprocess.Popen(
                [sys._base_executable, "-I", "-S", "-B", str(Path(__file__).resolve()),
                 *map(str, handles)],
                startupinfo=startup, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW,
            )
        signaled = None
        try:
            signaled = _winapi.WaitForMultipleObjects([ready, guard._handle], False, 10_000)
            if signaled != _winapi.WAIT_OBJECT_0:
                raise OSError("Windows campaign recovery observer did not become ready")
            yield
        finally:
            _check(_set_event(done))
            if signaled in (None, _winapi.WAIT_TIMEOUT):
                # No worker was released to a helper that failed to initialize.
                guard.kill()
            _, stderr = guard.communicate()
            if guard.returncode and signaled not in (None, _winapi.WAIT_TIMEOUT):
                raise OSError(f"Campaign recovery observer exited {guard.returncode}: "
                              f"{stderr.decode(errors='replace').strip()}")


def _observe(job: int, lease: int, supervisor: int, ready: int, done: int) -> None:
    try:
        _check(_set_event(ready))
        _winapi.WaitForMultipleObjects([supervisor, done], False, _winapi.INFINITE)
        stop_and_drain(job)
    finally:
        # The new supervisor may enter as soon as the last lease handle closes.
        # Close the job before releasing the lease, including on guard errors.
        _winapi.CloseHandle(job)
        _winapi.CloseHandle(lease)


@contextmanager
def job_object(ownership: tuple[str, int] | None, memory_limit_mb: int | None,
               *, after_drain: Callable[[int], None] | None = None) -> Iterator[int]:
    name = ownership[0] if ownership else None
    ct.set_last_error(0)
    handle = _check(_create_job(None, name))
    try:
        if name and ct.get_last_error() == _ERROR_ALREADY_EXISTS:
            raise OSError("Previous campaign job has not finished closing")
        limits = _ExtendedLimits()
        limits.basic.flags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if memory_limit_mb is not None:
            limits.basic.flags |= 0x00000200  # JOB_OBJECT_LIMIT_JOB_MEMORY (total commit)
            limits.job_memory = memory_limit_mb * 1024**2
        _check(_limit_job(handle, 9, ct.byref(limits), ct.sizeof(limits)))
        guard = _recovery_guard(handle, ownership[1]) if ownership else nullcontext()
        try:
            with guard:
                yield handle
        finally:
            # Ordinarily the observer drains first. The fallback also covers a
            # failed observer while the original supervisor still owns the job.
            stop_and_drain(handle)
            if after_drain is not None:
                after_drain(handle)
    finally:
        _winapi.CloseHandle(handle)


def _environment(values: dict[str, str]) -> ct.Array:
    entries = []
    for key, value in sorted(values.items(), key=lambda item: item[0].upper()):
        if not key or "=" in key[1:] or "\0" in key or "\0" in value:
            raise ValueError(f"Invalid Windows environment variable {key!r}")
        entries.append(f"{key}={value}")
    return ct.create_unicode_buffer("\0".join(entries) + "\0")


@contextmanager
def start_process(job: int, argv: list[str], cwd: Path, env: dict[str, str],
                  stdout_path: Path, stderr_path: Path) -> Iterator[int]:
    """Create with JOB_LIST and an explicit allowlist of three standard handles.

    Assigning an already-created process to the job leaves a supervisor-death
    window. JOB_LIST binds the worker in the kernel during CreateProcessW.
    """
    attrs_size = ct.c_size_t()
    _init_attrs(None, 2, 0, ct.byref(attrs_size))
    if ct.get_last_error() != 122:  # ERROR_INSUFFICIENT_BUFFER
        raise ct.WinError(ct.get_last_error())
    buf = ct.create_string_buffer(attrs_size.value)
    with ExitStack() as cleanup:
        _check(_init_attrs(buf, 2, 0, ct.byref(attrs_size)))
        cleanup.callback(_delete_attrs, buf)
        streams = (cleanup.enter_context(open(os.devnull, "rb")),
                   cleanup.enter_context(stdout_path.open("xb")),
                   cleanup.enter_context(stderr_path.open("xb")))
        std_handles = (wt.HANDLE * 3)(*(msvcrt.get_osfhandle(s.fileno()) for s in streams))
        for handle in std_handles:
            os.set_handle_inheritable(handle, True)
        jobs = (wt.HANDLE * 1)(job)
        _check(_set_attr(buf, 0, 0x00020002, std_handles, ct.sizeof(std_handles), None, None))
        _check(_set_attr(buf, 0, 0x0002000D, jobs, ct.sizeof(jobs), None, None))
        info = _StartupInfoEx()
        info.startup.cb = ct.sizeof(info)
        info.startup.flags = 0x00000100  # STARTF_USESTDHANDLES
        info.startup.stdin, info.startup.stdout, info.startup.stderr = std_handles
        info.attributes = ct.cast(buf, _pointer)
        process = _ProcessInfo()
        flags = 0x00080000 | subprocess.CREATE_NO_WINDOW | 0x00000400
        cmd = ct.create_unicode_buffer(subprocess.list2cmdline(argv))
        _check(_create_process(argv[0], cmd, None, None, True, flags, _environment(env),
                               str(cwd), ct.byref(info), ct.byref(process)))
        _winapi.CloseHandle(process.thread)
    try:
        yield process.process
    finally:
        _winapi.CloseHandle(process.process)


def wait_for_exit(handle: int, milliseconds: int) -> int | None:
    if _winapi.WaitForSingleObject(handle, milliseconds) == _winapi.WAIT_TIMEOUT:
        return None
    return _winapi.GetExitCodeProcess(handle)


if __name__ == "__main__":
    _observe(*map(int, sys.argv[1:]))
