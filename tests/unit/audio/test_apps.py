"""Tests de `audio/apps.py` (T008): lista de apps, búsqueda, raíz actual y tabla de procesos real.

La lógica de agrupar, ocultar y decidir «suena» se prueba con un inspector y un enumerador de sesiones
falsos, sin COM ni dispositivos. La tabla de procesos real (psutil) se prueba con procesos de verdad
(hijos de Python que duermen); no suena nada.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Sequence

import numpy as np
import pytest

from instanttraductor.audio import apps as apps_module
from instanttraductor.audio.app_types import AppIdentity, ProcessTable
from instanttraductor.audio.apps import (
    SOUNDING_DBFS,
    AudioSession,
    ProcessInfo,
    SystemProcessTable,
    file_description,
    find_app,
    list_audio_apps,
    resolve_root,
)
from instanttraductor.contracts import CAPTURE_RATE, AudioChunk, EngineError
from instanttraductor.pipeline.clock import ManualClock
from tests.contract.helpers import assert_implements
from tests.fakes.fake_apps import FakeAppEnumerator, FakeProcessTable, app

ME = 500
PARENT = 400  # lanzador / venv
GRANDPARENT = 300  # terminal

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
DISCORD = r"C:\Users\x\AppData\Local\Discord\app-1.0\Discord.exe"
FFPLAY = r"C:\tools\ffplay.exe"
TERMINAL = r"C:\Program Files\WindowsApps\wt.exe"


def db_to_rms(dbfs: float) -> float:
    return 10 ** (dbfs / 20)


class FakeInspector:
    """Tabla de procesos por guion para `list_audio_apps`: PID -> `ProcessInfo`."""

    def __init__(self, hidden: Sequence[int] = (ME, PARENT, GRANDPARENT)) -> None:
        self.procs: dict[int, ProcessInfo] = {}
        self._hidden = frozenset(hidden)
        self.names: dict[str, str] = {}

    def add(self, pid: int, exe: str, *, ppid: int = 1, created: float = 10.0) -> ProcessInfo:
        info = ProcessInfo(pid, created, ppid, exe, os.path.basename(exe))
        self.procs[pid] = info
        return info

    def info(self, pid: int) -> ProcessInfo | None:
        return self.procs.get(pid)

    def display_name(self, info: ProcessInfo) -> str:
        return self.names.get(info.exe, os.path.splitext(info.name)[0].capitalize())

    def hidden_pids(self) -> frozenset[int]:
        return self._hidden


def session(
    pid: int, *, endpoint: str = "Altavoces", state: int = 1, peak: float = 0.1, system: bool = False
):
    return AudioSession(endpoint, pid, state, peak, system)


def fake_probe(levels: dict[int, float]) -> Callable[[Sequence[int], float], dict[int, float]]:
    """Sonda falsa: RMS por PID objetivo; anota qué se sondeó y durante cuánto."""
    calls: list[tuple[list[int], float]] = []

    def probe(pids: Sequence[int], seconds: float) -> dict[int, float]:
        calls.append((list(pids), seconds))
        return {pid: levels.get(pid, 0.0) for pid in pids}

    probe.calls = calls  # type: ignore[attr-defined]
    return probe


def listing(
    inspector: FakeInspector,
    sessions: list[AudioSession],
    levels: dict[int, float] | None = None,
    *,
    probe_s: float = 0.6,
):
    probe = fake_probe(levels or {})
    result = list_audio_apps(
        probe_s=probe_s, enumerate_sessions=lambda: sessions, inspector=inspector, probe=probe
    )
    return result, probe


class TestListAudioApps:
    def test_groups_the_sessions_by_executable_and_merges_the_endpoints(self) -> None:
        inspector = FakeInspector()
        inspector.add(1000, CHROME)
        inspector.add(1001, CHROME, ppid=1000, created=11.0)
        result, _ = listing(
            inspector,
            [
                session(1000, endpoint="Altavoces"),
                session(1001, endpoint="Auriculares"),
                session(1000, endpoint="Auriculares"),
            ],
        )
        assert len(result) == 1
        assert result[0].identity.exe_path == CHROME
        assert result[0].endpoints == ("Altavoces", "Auriculares")

    def test_the_target_is_the_direct_parent_when_it_is_the_same_image_and_older(self) -> None:
        inspector = FakeInspector()
        inspector.add(2000, CHROME, created=5.0)  # browser
        inspector.add(2001, CHROME, ppid=2000, created=6.0)  # servicio de audio, el emisor
        result, probe = listing(inspector, [session(2001)])
        assert result[0].identity.root_pid == 2000
        assert result[0].identity.create_time == 5.0
        assert probe.calls[0][0] == [2000]

    def test_the_target_is_the_emitter_when_the_parent_is_another_image(self) -> None:
        inspector = FakeInspector()
        inspector.add(2000, r"C:\tools\launcher.exe", created=5.0)
        inspector.add(2001, FFPLAY, ppid=2000, created=6.0)
        result, _ = listing(inspector, [session(2001)])
        assert result[0].identity.root_pid == 2001

    def test_the_target_is_the_emitter_when_the_same_image_parent_is_newer(self) -> None:
        inspector = FakeInspector()
        inspector.add(
            2000, CHROME, created=9.0
        )  # PID reutilizado o más joven que el hijo: no es su padre real
        inspector.add(2001, CHROME, ppid=2000, created=6.0)
        result, _ = listing(inspector, [session(2001)])
        assert result[0].identity.root_pid == 2001

    def test_targets_that_are_direct_children_of_another_target_are_not_counted_twice(self) -> None:
        inspector = FakeInspector()
        inspector.add(3000, DISCORD, created=5.0)
        inspector.add(3001, r"C:\x\Update.exe", ppid=3000, created=6.0)  # otra imagen: no se agrupa
        inspector.add(3002, DISCORD, ppid=3001, created=7.0)  # el padre es otra imagen: es su propio objetivo
        result, probe = listing(inspector, [session(3000), session(3002)])
        assert len(result) == 1
        assert sorted(probe.calls[0][0]) == [3000, 3002]

    def test_the_own_app_and_all_its_ancestors_are_hidden(self) -> None:
        inspector = FakeInspector()
        inspector.add(GRANDPARENT, TERMINAL)
        inspector.add(PARENT, r"C:\venv\python.exe", ppid=GRANDPARENT, created=11.0)
        inspector.add(ME, r"C:\py\python.exe", ppid=PARENT, created=12.0)
        inspector.add(1000, CHROME)
        result, _ = listing(inspector, [session(ME), session(PARENT), session(GRANDPARENT), session(1000)])
        assert [a.identity.exe_path for a in result] == [CHROME]

    def test_a_session_whose_target_is_an_ancestor_is_hidden_too(self) -> None:
        inspector = FakeInspector()
        inspector.add(PARENT, r"C:\venv\python.exe", created=5.0)  # lanzador del venv
        inspector.add(1500, r"C:\venv\python.exe", ppid=PARENT, created=6.0)  # otro proceso suyo que suena
        inspector.add(1000, CHROME)
        result, _ = listing(inspector, [session(1500), session(1000)])
        assert [a.identity.exe_path for a in result] == [CHROME]

    def test_system_sessions_pid_zero_unknown_processes_and_unreadable_images_are_skipped(self) -> None:
        inspector = FakeInspector()
        inspector.add(1000, CHROME)
        inspector.add(1100, "")  # imagen protegida: sin ruta no hay identidad
        result, _ = listing(
            inspector,
            [
                session(1000, system=True),
                session(0),
                session(9999),  # el proceso ya no existe
                session(1100),
            ],
        )
        assert result == []

    def test_an_app_sounds_when_the_include_probe_reaches_minus_60_dbfs(self) -> None:
        inspector = FakeInspector()
        inspector.add(1000, CHROME)
        inspector.add(1100, DISCORD)
        inspector.add(1200, FFPLAY)
        levels = {1000: db_to_rms(SOUNDING_DBFS + 0.5), 1100: db_to_rms(SOUNDING_DBFS - 0.5), 1200: 0.0}
        result, _ = listing(inspector, [session(1000), session(1100), session(1200)], levels)
        by_path = {a.identity.exe_path: a for a in result}
        assert by_path[CHROME].sounding is True
        assert by_path[DISCORD].sounding is False  # el medidor marca, pero la captura no llega a -60 dBFS
        assert by_path[FFPLAY].sounding is False
        assert by_path[CHROME].level_dbfs == pytest.approx(SOUNDING_DBFS + 0.5, abs=0.01)

    def test_the_peak_meter_alone_does_not_make_an_app_sound(self) -> None:
        inspector = FakeInspector()
        inspector.add(1100, DISCORD)
        result, _ = listing(inspector, [session(1100, peak=0.9)], {1100: 0.0})
        assert result[0].sounding is False

    def test_only_candidates_with_an_active_session_or_a_peak_are_probed(self) -> None:
        inspector = FakeInspector()
        inspector.add(1000, CHROME)
        inspector.add(1100, DISCORD)
        inspector.add(1200, FFPLAY)
        result, probe = listing(
            inspector,
            [
                session(1000, state=1, peak=0.0),  # activa
                session(1100, state=0, peak=0.5),  # inactiva con pico
                session(1200, state=0, peak=0.0),  # inactiva y sin pico: no se sondea
            ],
        )
        assert sorted(probe.calls[0][0]) == [1000, 1100]
        assert probe.calls[0][1] == pytest.approx(0.6)
        assert len(result) == 3

    def test_the_probe_duration_is_passed_on_and_zero_skips_the_probe(self) -> None:
        inspector = FakeInspector()
        inspector.add(1000, CHROME)
        _, probe = listing(inspector, [session(1000)], probe_s=1.2)
        assert probe.calls[0][1] == pytest.approx(1.2)
        result, probe = listing(inspector, [session(1000)], {1000: 0.5}, probe_s=0.0)
        assert probe.calls == []
        assert result[0].sounding is False

    def test_the_ones_that_sound_come_first_ordered_by_level_then_by_name(self) -> None:
        inspector = FakeInspector()
        inspector.names = {
            CHROME: "Google Chrome",
            DISCORD: "Discord",
            FFPLAY: "ffplay",
            r"C:\a\Zeta.exe": "Zeta",
        }
        inspector.add(1000, CHROME)
        inspector.add(1100, DISCORD)
        inspector.add(1200, FFPLAY)
        inspector.add(1300, r"C:\a\Zeta.exe")
        levels = {1000: db_to_rms(-30), 1100: db_to_rms(-20)}
        result, _ = listing(inspector, [session(p) for p in (1000, 1100, 1200, 1300)], levels)
        assert [a.identity.display_name for a in result] == ["Discord", "Google Chrome", "ffplay", "Zeta"]

    def test_with_several_instances_the_identity_is_the_loudest_one(self) -> None:
        inspector = FakeInspector()
        inspector.add(1000, CHROME, created=1.0)
        inspector.add(1100, CHROME, created=2.0)
        result, _ = listing(inspector, [session(1000), session(1100)], {1000: 0.0, 1100: 0.05})
        assert len(result) == 1
        assert result[0].identity.root_pid == 1100

    def test_with_several_silent_instances_the_identity_is_the_oldest_one(self) -> None:
        inspector = FakeInspector()
        inspector.add(1100, CHROME, created=2.0)
        inspector.add(1000, CHROME, created=1.0)
        result, _ = listing(inspector, [session(1100), session(1000)])
        assert result[0].identity.root_pid == 1000

    def test_the_display_name_comes_from_the_inspector(self) -> None:
        inspector = FakeInspector()
        inspector.names = {CHROME: "Google Chrome"}
        inspector.add(1000, CHROME)
        result, _ = listing(inspector, [session(1000)])
        assert result[0].identity.display_name == "Google Chrome"

    def test_a_failing_enumeration_gives_an_empty_list(self) -> None:
        def boom() -> list[AudioSession]:
            raise OSError("sin dispositivos")

        assert list_audio_apps(enumerate_sessions=boom, inspector=FakeInspector()) == []

    def test_a_failing_probe_keeps_the_apps_as_not_sounding(self) -> None:
        inspector = FakeInspector()
        inspector.add(1000, CHROME)

        def boom(pids: Sequence[int], seconds: float) -> dict[int, float]:
            raise EngineError("sin captura", engine="capture")

        result = list_audio_apps(enumerate_sessions=lambda: [session(1000)], inspector=inspector, probe=boom)
        assert len(result) == 1
        assert result[0].sounding is False


class TestFindApp:
    def enumerator(self) -> FakeAppEnumerator:
        chrome = app(CHROME, name="Google Chrome", pid=10)
        discord = app(DISCORD, name="Discord", pid=20)
        return FakeAppEnumerator(
            [
                apps_module.AudioApp(chrome, True, -20.0, ("Altavoces",)),
                apps_module.AudioApp(discord, False, -90.0),
            ]
        )

    class NoProcesses:
        def find_by_name(self, fragment: str) -> list[ProcessInfo]:
            return []

    def test_matches_by_visible_name_without_distinguishing_case(self) -> None:
        found = find_app("GOOGLE chrome", enumerate_apps=self.enumerator(), table=self.NoProcesses())
        assert [a.exe_path for a in found] == [CHROME]

    def test_matches_by_executable_name(self) -> None:
        for query in ("chrome", "Chrome.EXE", "discord.exe"):
            found = find_app(query, enumerate_apps=self.enumerator(), table=self.NoProcesses())
            assert len(found) == 1, query

    def test_matches_by_the_exact_path_in_any_case(self) -> None:
        found = find_app(CHROME.upper(), enumerate_apps=self.enumerator(), table=self.NoProcesses())
        assert [a.exe_path for a in found] == [CHROME]

    def test_the_listing_is_requested_without_a_probe(self) -> None:
        enumerator = self.enumerator()
        seen: list[float] = []

        def spy(*, probe_s: float = 0.6):
            seen.append(probe_s)
            return enumerator(probe_s=probe_s)

        find_app("chrome", enumerate_apps=spy, table=self.NoProcesses())
        assert seen == [0]

    def test_nothing_matches_gives_an_empty_list(self) -> None:
        assert find_app("firefox", enumerate_apps=self.enumerator(), table=self.NoProcesses()) == []
        assert find_app("   ", enumerate_apps=self.enumerator(), table=self.NoProcesses()) == []

    def test_adds_running_processes_that_have_no_audio_session_yet_without_duplicates(self) -> None:
        class Running:
            def find_by_name(self, fragment: str) -> list[ProcessInfo]:
                return [
                    ProcessInfo(77, 3.0, 1, CHROME, "chrome.exe"),  # ya está en la lista de sesiones
                    ProcessInfo(88, 4.0, 1, r"C:\Mozilla\firefox.exe", "firefox.exe"),
                ]

        found = find_app("chrome", enumerate_apps=self.enumerator(), table=Running())
        assert [a.exe_path for a in found] == [CHROME, r"C:\Mozilla\firefox.exe"]
        assert found[0].root_pid == 10  # la de la lista (con sesión) manda sobre el proceso suelto
        assert found[1].root_pid == 88


class TestResolveRoot:
    def test_gives_the_oldest_live_root_with_its_current_pid_and_creation_time(self) -> None:
        clock = ManualClock(5.0)
        table = FakeProcessTable(
            clock,
            [
                (app(CHROME, pid=40, create_time=3.0), 0.0, None),
                (app(CHROME, pid=30, create_time=2.0), 0.0, None),
            ],
        )
        found = resolve_root(CHROME, table=table)
        assert found is not None
        assert (found.root_pid, found.create_time) == (30, 2.0)

    def test_is_none_when_the_app_is_not_running(self) -> None:
        assert resolve_root(CHROME, table=FakeProcessTable(ManualClock())) is None

    def test_follows_a_restart(self) -> None:
        clock = ManualClock()
        table = FakeProcessTable(
            clock,
            [
                (app(CHROME, pid=1, create_time=1.0), 0.0, 2.0),
                (app(CHROME, pid=2, create_time=2.0), 3.0, None),
            ],
        )
        first = resolve_root(CHROME, table=table)
        assert first is not None and first.root_pid == 1
        clock.set(2.5)
        assert resolve_root(CHROME, table=table) is None
        clock.set(3.5)
        second = resolve_root(CHROME, table=table)
        assert second is not None and second.root_pid == 2


class FakeSource:
    """Sustituto de `ProcessLoopbackSource` para la sonda: entrega unos chunks y se para."""

    created: list[FakeSource] = []
    level_by_pid: dict[int, float] = {}
    fail_pids: set[int] = set()

    def __init__(self, clock: object, *, include: bool = False, target_pid: int | None = None, **_: object):
        assert include is True, "la sonda debe ser INCLUDE"
        self.pid = target_pid
        self.stopped = False
        self._left = 5
        FakeSource.created.append(self)

    def start(self) -> None:
        if self.pid in FakeSource.fail_pids:
            raise EngineError("no se pudo abrir", engine="capture")

    def read(self, timeout: float) -> AudioChunk | None:
        if self._left == 0:
            return None
        self._left -= 1
        level = FakeSource.level_by_pid.get(self.pid or 0, 0.0)
        samples = np.full(int(0.02 * CAPTURE_RATE), level, dtype=np.float32)
        return AudioChunk(samples, CAPTURE_RATE, 0.0)

    def stop(self) -> None:
        self.stopped = True


class TestIncludeProbe:
    @pytest.fixture(autouse=True)
    def fake_source(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
        FakeSource.created, FakeSource.level_by_pid, FakeSource.fail_pids = [], {}, set()
        monkeypatch.setattr(apps_module, "ProcessLoopbackSource", FakeSource)
        monkeypatch.setattr(apps_module.time, "sleep", lambda s: None)
        yield

    def test_measures_the_rms_of_each_include_capture_and_stops_them_all(self) -> None:
        FakeSource.level_by_pid = {10: 0.01, 20: 0.0}
        rms = apps_module._probe_include([10, 20], 0.6)
        assert rms[10] == pytest.approx(0.01, rel=1e-3)
        assert rms[20] == 0.0
        assert all(source.stopped for source in FakeSource.created)

    def test_a_capture_that_cannot_be_opened_gives_zero_and_does_not_stop_the_others(self) -> None:
        FakeSource.level_by_pid = {10: 0.02, 20: 0.02}
        FakeSource.fail_pids = {10}
        rms = apps_module._probe_include([10, 20], 0.6)
        assert rms[10] == 0.0
        assert rms[20] == pytest.approx(0.02, rel=1e-3)


class TestSystemProcessTable:
    @pytest.fixture
    def sleeper(self) -> Iterator[subprocess.Popen[bytes]]:
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        time.sleep(0.3)
        yield process
        process.kill()
        process.wait()

    def test_implements_the_process_table_protocol(self) -> None:
        assert_implements(SystemProcessTable(), ProcessTable)

    def test_hidden_pids_are_the_own_process_and_every_ancestor(self) -> None:
        import psutil

        hidden = SystemProcessTable().hidden_pids()
        assert os.getpid() in hidden
        assert {p.pid for p in psutil.Process().parents()} <= hidden

    def test_info_of_the_own_process(self) -> None:
        info = SystemProcessTable().info(os.getpid())
        assert info is not None
        assert info.pid == os.getpid()
        assert info.name.lower().startswith("python")
        assert info.exe
        assert info.create_time > 0

    def test_info_of_a_process_that_does_not_exist_is_none(self) -> None:
        assert SystemProcessTable().info(4_000_000) is None

    def test_is_alive_distinguishes_a_reused_pid_by_its_creation_time(self, sleeper) -> None:
        table = SystemProcessTable()
        info = table.info(sleeper.pid)
        assert info is not None
        assert table.is_alive(info.pid, info.create_time) is True
        assert table.is_alive(info.pid, info.create_time + 1.0) is False  # mismo PID, otro proceso
        sleeper.kill()
        sleeper.wait()
        assert table.is_alive(info.pid, info.create_time) is False

    def test_find_roots_finds_a_live_process_by_its_image_and_resolve_root_agrees(self, sleeper) -> None:
        table = SystemProcessTable()
        info = table.info(sleeper.pid)
        assert info is not None and info.exe
        roots = table.find_roots(info.exe)
        assert sleeper.pid in {r.root_pid for r in roots}
        root = next(r for r in roots if r.root_pid == sleeper.pid)
        assert (root.create_time, root.exe_path) == (info.create_time, info.exe)
        assert [r.create_time for r in roots] == sorted(r.create_time for r in roots)
        found = resolve_root(info.exe, table=table)
        assert found is not None and found.exe_path.lower() == info.exe.lower()

    def test_find_roots_never_offers_the_own_process_or_its_ancestors(self) -> None:
        table = SystemProcessTable()
        own = table.info(os.getpid())
        assert own is not None
        assert os.getpid() not in {r.root_pid for r in table.find_roots(own.exe)}

    def test_find_roots_of_an_app_that_is_not_running_is_empty(self) -> None:
        assert SystemProcessTable().find_roots(r"C:\no\existe\nada_de_nada.exe") == []

    def test_find_by_name_finds_a_running_process_by_a_fragment(self, sleeper) -> None:
        info = SystemProcessTable().info(sleeper.pid)
        assert info is not None
        found = SystemProcessTable().find_by_name(os.path.splitext(info.name)[0][:5])
        assert sleeper.pid in {p.pid for p in found}


def test_file_description_of_a_system_executable_and_of_a_missing_one() -> None:
    cmd = os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32", "cmd.exe")
    assert file_description(cmd) != ""
    assert file_description(r"C:\no\existe\nada.exe") == ""
    assert file_description("") == ""


def test_the_fake_enumerator_and_identity_helpers_fit_the_real_types() -> None:
    identity = app(CHROME)
    assert isinstance(identity, AppIdentity)
    assert FakeAppEnumerator()(probe_s=0.0) == []
