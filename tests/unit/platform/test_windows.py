"""Tests de ``platform/windows.py``: Job Object, lanzamiento de hijos, versión de Windows y teclas.

Son tests de procesos reales del sistema (sin hardware de audio ni GPU).
"""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import psutil
import pytest

from instanttraductor.platform import windows

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Solo para Windows")

SLEEPER = [sys.executable, "-c", "import time; time.sleep(60)"]


def _wait_until_gone(pid: int, timeout_s: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while psutil.pid_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    return not psutil.pid_exists(pid)


# ---------------------------------------------------------------------------
# Job Object
# ---------------------------------------------------------------------------
def test_child_dies_within_2s_when_the_job_closes() -> None:
    proc = windows.launch_child(SLEEPER)
    assert proc.poll() is None

    start = time.monotonic()
    windows.close_job()
    proc.wait(timeout=2.0)  # TimeoutExpired si el hijo sigue vivo

    assert time.monotonic() - start <= 2.0
    assert proc.poll() is not None


def test_descendants_of_the_child_die_with_the_job() -> None:
    code = (
        "import subprocess, sys, time\n"
        "grandchild = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "print(grandchild.pid, flush=True)\n"
        "time.sleep(60)\n"
    )
    proc = windows.launch_child([sys.executable, "-c", code])
    assert proc.stdout is not None
    grandchild_pid = int(proc.stdout.readline())
    assert psutil.pid_exists(grandchild_pid)

    windows.close_job()

    proc.wait(timeout=2.0)
    assert _wait_until_gone(grandchild_pid), "el nieto sigue vivo: quedaría un proceso huérfano"


def test_all_children_share_one_job() -> None:
    first = windows.launch_child(SLEEPER)
    second = windows.launch_child(SLEEPER)

    windows.close_job()  # un solo cierre mata a los dos

    first.wait(timeout=2.0)
    second.wait(timeout=2.0)


def test_close_job_is_idempotent_and_the_next_launch_creates_a_new_job() -> None:
    windows.close_job()  # sin job: no hace nada
    first = windows.launch_child(SLEEPER)
    windows.close_job()
    windows.close_job()  # segunda vez: tampoco falla
    first.wait(timeout=2.0)

    second = windows.launch_child(SLEEPER)  # job nuevo
    assert second.poll() is None
    windows.close_job()
    second.wait(timeout=2.0)


def test_created_job_has_the_kill_on_close_flag() -> None:
    job = windows.create_kill_on_close_job()
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.QueryInformationJobObject.restype = wintypes.BOOL
        k32.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        info = windows._ExtendedLimitInfo()
        job_object_extended_limit_information = 9
        assert k32.QueryInformationJobObject(
            job._handle, job_object_extended_limit_information, ctypes.byref(info), ctypes.sizeof(info), None
        )
        assert info.BasicLimitInformation.LimitFlags & windows.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    finally:
        job.close()


def test_a_standalone_job_kills_its_process_when_closed() -> None:
    job = windows.create_kill_on_close_job()
    proc = subprocess.Popen(SLEEPER)
    try:
        job.assign(proc)
        job.close()
        assert job.closed
        proc.wait(timeout=2.0)
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()


def test_assigning_to_a_closed_job_raises_oserror() -> None:
    job = windows.create_kill_on_close_job()
    job.close()
    proc = subprocess.Popen(SLEEPER)
    try:
        with pytest.raises(OSError):
            job.assign(proc)
    finally:
        proc.kill()
        proc.wait()


def test_launch_child_kills_the_child_if_it_cannot_join_the_job(monkeypatch: pytest.MonkeyPatch) -> None:
    closed_job = windows.create_kill_on_close_job()
    closed_job.close()
    monkeypatch.setattr(windows, "_shared_job", lambda: closed_job)
    spawned: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    def spy(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(subprocess, "Popen", spy)

    with pytest.raises(OSError):
        windows.launch_child(SLEEPER)

    assert len(spawned) == 1
    assert spawned[0].poll() is not None  # el hijo no se queda corriendo fuera del job


# ---------------------------------------------------------------------------
# launch_child: opciones del proceso
# ---------------------------------------------------------------------------
def test_launch_child_uses_no_window_and_pipes(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}
    real_popen = subprocess.Popen

    def spy(*args, **kwargs):
        captured.update(kwargs)
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", spy)

    code = "import sys; print('salida'); print('error', file=sys.stderr)"
    proc = windows.launch_child([sys.executable, "-c", code])
    stdout, stderr = proc.communicate(timeout=20)

    assert captured["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert captured["stdout"] == subprocess.PIPE
    assert captured["stderr"] == subprocess.PIPE
    assert stdout.strip() == "salida"
    assert stderr.strip() == "error"


def test_launch_child_adds_env_to_the_current_environment_and_sets_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("IT_PARENT_VAR", "padre")
    code = (
        "import os; e = os.environ; print(e['IT_CHILD_VAR']); print(e['IT_PARENT_VAR']); print(os.getcwd())"
    )

    proc = windows.launch_child([sys.executable, "-c", code], env={"IT_CHILD_VAR": "hijo"}, cwd=tmp_path)
    stdout, _ = proc.communicate(timeout=20)

    child_var, parent_var, child_cwd = stdout.split("\n")[:3]
    assert child_var == "hijo"
    assert parent_var == "padre"  # el entorno del padre se conserva
    assert os.path.samefile(child_cwd, tmp_path)


def test_launch_child_decodes_invalid_bytes_instead_of_failing() -> None:
    code = "import sys; sys.stdout.buffer.write(b'a\\xffb\\n'); sys.stdout.flush()"

    proc = windows.launch_child([sys.executable, "-c", code])
    stdout, _ = proc.communicate(timeout=20)

    assert stdout.strip() == "a�b"


# ---------------------------------------------------------------------------
# Versión de Windows
# ---------------------------------------------------------------------------
def test_windows_build_is_the_running_systems_build() -> None:
    build = windows.windows_build()

    assert isinstance(build, int)
    assert build == sys.getwindowsversion().build
    assert build >= 10240  # Windows 10 o posterior (la preparación exige >= 20348)


def test_windows_build_is_zero_outside_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(sys, "getwindowsversion")

    assert windows.windows_build() == 0


# ---------------------------------------------------------------------------
# Teclado (msvcrt)
# ---------------------------------------------------------------------------
class FakeMsvcrt:
    """Teclado de consola falso: ``kbhit`` indica si quedan teclas y ``getwch`` las entrega."""

    def __init__(self, keys: str | list[str]) -> None:
        self.keys = list(keys)

    def kbhit(self) -> bool:
        return bool(self.keys)

    def getwch(self) -> str:
        return self.keys.pop(0)


def test_read_key_returns_none_when_no_key_is_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(windows, "msvcrt", FakeMsvcrt(""))

    assert windows.read_key_nonblocking() is None


def test_read_key_returns_one_key_per_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(windows, "msvcrt", FakeMsvcrt("+-tq"))

    assert [windows.read_key_nonblocking() for _ in range(5)] == ["+", "-", "t", "q", None]


@pytest.mark.parametrize("prefix", ["\x00", "\xe0"])
def test_special_keys_are_consumed_and_ignored(monkeypatch: pytest.MonkeyPatch, prefix: str) -> None:
    fake = FakeMsvcrt([prefix, "H", "q"])  # flecha arriba y después una «q»
    monkeypatch.setattr(windows, "msvcrt", fake)

    assert windows.read_key_nonblocking() is None
    assert fake.keys == ["q"]  # el segundo código de la flecha se consumió
    assert windows.read_key_nonblocking() == "q"


def test_read_key_without_msvcrt_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(windows, "msvcrt", None)

    assert windows.read_key_nonblocking() is None


def test_read_key_with_the_real_msvcrt_does_not_block() -> None:
    key = windows.read_key_nonblocking()  # bajo pytest no hay una tecla pendiente

    assert key is None or isinstance(key, str)


def test_msvcrt_is_only_imported_by_platform_windows() -> None:
    """Principio VII: ``platform/windows.py`` es el único sitio del núcleo que lee teclas."""
    source_root = Path(windows.__file__).resolve().parents[1]
    pattern = re.compile(r"^\s*(import\s+msvcrt\b|from\s+msvcrt\s+import\b)", re.MULTILINE)

    importers = {
        path.relative_to(source_root).as_posix()
        for path in source_root.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    }

    assert importers == {"platform/windows.py"}
