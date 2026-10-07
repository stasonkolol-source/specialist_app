"""Самовосстановление dev-стенда (scripts/dev.py): проверка туннелей и перезапуск процессов.

Сеть не нужна: `reachable` проверяется на локальном HTTP-сервере, решения смотрителя — на
фейках туннелей и процессов. Остановка группы процессов — на настоящих `sleep`.
"""

import importlib
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS))
dev: Any = importlib.import_module("dev")


class StatusHandler(BaseHTTPRequestHandler):
    """HEAD /<код> отвечает этим кодом — как Vite, Garage или Cloudflare без туннеля."""

    def do_HEAD(self) -> None:
        self.send_response(int(self.path.strip("/")))
        self.end_headers()

    def log_message(self, *_args: object) -> None:
        return None


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), StatusHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()


@pytest.mark.parametrize(
    ("status", "alive"),
    [(200, True), (403, True), (502, True), (530, False)],
    ids=["vite", "garage-403", "app-restarting-502", "cloudflare-tunnel-down"],
)
def test_any_answer_but_530_means_tunnel_alive(server: str, status: int, alive: bool) -> None:
    assert dev.reachable(f"{server}/{status}") is alive


def test_nobody_listening_means_unreachable() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert dev.reachable(f"http://127.0.0.1:{port}/", timeout=2) is False


@dataclass
class FakeProcess:
    code: int | None = None

    def poll(self) -> int | None:
        return self.code


@dataclass
class FakeTunnel:
    name: str
    url: str
    process: FakeProcess = field(default_factory=FakeProcess)


@dataclass
class World:
    """Состояние сети для смотрителя: какие адреса отвечают и есть ли интернет."""

    online: bool = True
    alive: set[str] = field(default_factory=set)
    opened: int = 0
    closed: list[list[str]] = field(default_factory=list)
    restarts: list[str] = field(default_factory=list)
    fail_open: bool = False

    def probe(self, url: str) -> bool:
        if url == dev.ONLINE_PROBE:
            return self.online
        return self.online and url in self.alive

    def opener(self) -> list[FakeTunnel]:
        if self.fail_open:
            raise SystemExit("tunnel app: no URL in 90s")
        self.opened += 1
        tunnels = [
            FakeTunnel("app", f"https://app-{self.opened}.example"),
            FakeTunnel("garage", f"https://s3-{self.opened}.example"),
        ]
        self.alive |= {t.url for t in tunnels}
        return tunnels

    def closer(self, tunnels: list[FakeTunnel]) -> None:
        self.closed.append([t.url for t in tunnels])


def stand(world: World) -> Any:
    s = dev.Stand(tunnels=True, probe=world.probe, opener=world.opener, closer=world.closer)
    s.restart_apps = world.restarts.append  # процессы здесь не нужны: только факт перезапуска
    assert s.open_tunnels()
    return s


def test_healthy_tunnels_change_nothing() -> None:
    world = World()
    s = stand(world)

    for _ in range(5):
        s.check_tunnels()

    assert (world.opened, world.closed, world.restarts) == (1, [], [])


def test_dead_tunnel_is_recreated_after_three_failures_and_apps_restart() -> None:
    world = World()
    s = stand(world)
    world.alive.discard("https://app-1.example")  # Cloudflare удалил quick tunnel

    s.check_tunnels()
    s.check_tunnels()
    assert world.opened == 1  # два провала — ещё ждём
    s.check_tunnels()

    assert world.closed == [["https://app-1.example", "https://s3-1.example"]]
    assert world.opened == 2
    assert [t.url for t in s.tunnels] == ["https://app-2.example", "https://s3-2.example"]
    assert world.restarts == ["new tunnel addresses"]
    assert s.failures == 0


def test_offline_does_not_count_as_dead_tunnel() -> None:
    world = World()
    s = stand(world)
    world.online = False  # Мак спит или нет Wi-Fi: туннель проверить нельзя

    for _ in range(10):
        s.check_tunnels()

    assert (world.opened, world.closed, world.restarts, s.failures) == (1, [], [], 0)


def test_failure_counter_resets_when_tunnel_recovers() -> None:
    world = World()
    s = stand(world)
    world.alive.discard("https://app-1.example")
    s.check_tunnels()
    s.check_tunnels()
    world.alive.add("https://app-1.example")  # связь вернулась, Cloudflare туннель помнит

    s.check_tunnels()
    world.alive.discard("https://app-1.example")
    s.check_tunnels()
    s.check_tunnels()

    assert world.opened == 1
    assert s.failures == 2


def test_dead_cloudflared_process_counts_as_failure() -> None:
    world = World()
    s = stand(world)
    s.tunnels[1].process.code = 1  # cloudflared туннеля Garage упал

    for _ in range(3):
        s.check_tunnels()

    assert world.opened == 2
    assert world.restarts == ["new tunnel addresses"]


def test_failed_recreation_is_retried_on_next_check() -> None:
    world = World()
    s = stand(world)
    world.alive.clear()
    world.fail_open = True
    for _ in range(3):
        s.check_tunnels()
    assert s.tunnels == []
    assert world.restarts == []  # адресов нет — процессы не трогаем

    world.fail_open = False
    s.check_tunnels()

    assert world.opened == 2
    assert world.restarts == ["new tunnel addresses"]


class ScriptedApps:
    """Запуски honcho по сценарию: у каждого — свои ответы poll(), последний повторяется."""

    def __init__(self, *runs: list[int | None]) -> None:
        self.runs = list(runs)
        self.spawned = 0

    def __call__(self) -> Any:
        polls = self.runs[min(self.spawned, len(self.runs) - 1)]
        self.spawned += 1
        answers = iter(polls)
        last: list[int | None] = [None]

        class Apps:
            pid = -1  # не настоящий процесс: стенд не должен слать ему сигналы

            @staticmethod
            def poll() -> int | None:
                last[0] = next(answers, last[0])
                return last[0]

        return Apps()


def scripted_stand(world: World, apps: ScriptedApps, monkeypatch: pytest.MonkeyPatch) -> Any:
    s = dev.Stand(
        tunnels=True, probe=world.probe, opener=world.opener, closer=world.closer, apps=apps
    )
    stops: list[int] = []
    monkeypatch.setattr(s, "stop_apps", lambda: stops.append(1))
    s.stops = stops
    return s


def test_clean_exit_of_apps_stops_the_stand(monkeypatch: pytest.MonkeyPatch) -> None:
    world = World()
    apps = ScriptedApps([None, 0])
    s = scripted_stand(world, apps, monkeypatch)

    assert s.run(tick=0, check_every=3600) == 0
    assert apps.spawned == 1


def test_crashed_apps_are_restarted_when_online(monkeypatch: pytest.MonkeyPatch) -> None:
    # бот упал: Telegram не ответил (VPN, обрыв сети) — honcho погасил весь стенд
    world = World()
    apps = ScriptedApps([None, 1], [None, None, 0])
    s = scripted_stand(world, apps, monkeypatch)

    assert s.run(tick=0, check_every=3600, restart_delays=(0.0,)) == 0
    assert apps.spawned == 2
    assert s.stops == [1]  # перед новым запуском добиты дети упавшего honcho


def test_crash_while_offline_waits_for_the_network(monkeypatch: pytest.MonkeyPatch) -> None:
    world = World(online=False)
    checks: list[bool] = []

    def probe(url: str) -> bool:
        if url == dev.ONLINE_PROBE:
            if len(checks) == 2:
                world.online = True  # связь вернулась
            checks.append(world.online)
            return world.online
        return world.probe(url)

    monkeypatch.setattr(dev, "OFFLINE_RECHECK", 0.0)
    apps = ScriptedApps([None, 1], [None, 0])
    s = dev.Stand(tunnels=False, probe=probe, apps=apps)
    monkeypatch.setattr(s, "stop_apps", lambda: None)

    assert s.run(tick=0, check_every=3600, restart_delays=(0.0,), max_crashes=1) == 0
    assert checks[:3] == [False, False, True]  # без сети не перезапускали и попытку не тратили
    assert apps.spawned == 2


def test_crash_loop_stops_the_stand(monkeypatch: pytest.MonkeyPatch) -> None:
    # падает снова и снова при живой сети — это ошибка в коде, а не связь: стенд останавливается
    world = World()
    apps = ScriptedApps([3])
    s = scripted_stand(world, apps, monkeypatch)

    assert s.run(tick=0, check_every=3600, restart_delays=(0.0,), max_crashes=2) == 3
    assert apps.spawned == 3


def test_fake_pids_never_get_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(dev.os, "kill", lambda pid, sig: sent.append((pid, sig)))

    dev._signal(-1, dev.signal.SIGTERM)
    dev._signal(0, dev.signal.SIGTERM)

    assert sent == []
    assert dev._alive(-1) is False


def test_restart_request_restarts_apps_without_touching_tunnels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = World()
    polls = iter([None, 0])

    class Apps:
        pid = -1

        @staticmethod
        def poll() -> int | None:
            return next(polls)

    s = dev.Stand(
        tunnels=True, probe=world.probe, opener=world.opener, closer=world.closer, apps=Apps
    )
    restarts: list[str] = []
    monkeypatch.setattr(s, "restart_apps", restarts.append)
    s.restart_requested = True

    s.run(tick=0, check_every=3600)

    assert restarts == ["make dev-restart"]
    assert (world.opened, world.closed) == (1, [])


HONCHO_LIKE = """
import subprocess, sys, time
# как honcho: каждый процесс — в своей сессии, у него свой потомок
subprocess.Popen(
    [sys.executable, "-c", "import subprocess, sys, time; "
     "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); time.sleep(60)"],
    start_new_session=True,
)
time.sleep(60)
"""

STUBBORN = """
import signal, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)  # воркер, который не выходит по SIGTERM
time.sleep(60)
"""


def spawn(code: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen([sys.executable, "-c", code], start_new_session=True)


def wait_for_children(pid: int, count: int) -> list[int]:
    for _ in range(100):
        tree = dev._descendants(pid)
        if len(tree) >= count:
            return tree
        time.sleep(0.05)
    raise AssertionError(f"expected {count} descendants of {pid}")


def test_stop_apps_kills_children_in_other_sessions() -> None:
    """honcho держит процессы в своих сессиях: сигнал его группе до них не доходит, и
    упавший honcho оставил бы сирот. Остановка идёт по дереву ppid."""
    s = dev.Stand(tunnels=False, apps=lambda: spawn(HONCHO_LIKE))
    s.start_apps()
    leader = s._apps.pid
    tree = [leader, *wait_for_children(leader, 2)]

    s.stop_apps()

    assert [pid for pid in tree if dev._alive(pid)] == []


def test_process_ignoring_sigterm_gets_sigkill(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dev, "APPS_STOP_TIMEOUT", 0.5)
    s = dev.Stand(tunnels=False, apps=lambda: spawn(STUBBORN))
    s.start_apps()
    pid = s._apps.pid
    time.sleep(0.3)  # успел поставить обработчик SIGTERM

    s.stop_apps()

    assert not dev._alive(pid)


def test_failed_tunnel_check_does_not_stop_the_stand() -> None:
    """Сбой проверки или пересоздания туннеля пишется в лог; стенд продолжает работать."""
    world = World()
    polls = iter([None, None, 0])

    class Apps:
        pid = -1

        @staticmethod
        def poll() -> int | None:
            return next(polls)

    s = dev.Stand(
        tunnels=True, probe=world.probe, opener=world.opener, closer=world.closer, apps=Apps
    )

    def broken() -> None:
        raise RuntimeError("Operation not permitted")

    s.check_tunnels = broken

    assert s.run(tick=0, check_every=0) == 0
