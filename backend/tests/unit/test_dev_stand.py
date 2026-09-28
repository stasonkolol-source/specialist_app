"""Самовосстановление dev-стенда (scripts/dev.py): проверка туннелей и перезапуск процессов.

Сеть не нужна: `reachable` проверяется на локальном HTTP-сервере, решения смотрителя — на
фейках туннелей и процессов. Остановка группы процессов — на настоящих `sleep`.
"""

import importlib
import os
import socket
import subprocess
import sys
import threading
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


def test_run_returns_exit_code_of_apps() -> None:
    world = World()
    apps = FakeProcess()

    class Apps:
        pid = -1

        @staticmethod
        def poll() -> int | None:
            apps.code = 3  # honcho завершился сам (упал web)
            return apps.code

    s = dev.Stand(
        tunnels=True, probe=world.probe, opener=world.opener, closer=world.closer, apps=Apps
    )

    assert s.run(tick=0, check_every=3600) == 3


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


def test_stop_apps_kills_whole_process_group() -> None:
    def spawn() -> subprocess.Popen[bytes]:
        # honcho с детьми: лидер группы и процесс-потомок
        return subprocess.Popen(["/bin/sh", "-c", "sleep 60 & sleep 60"], start_new_session=True)

    s = dev.Stand(tunnels=False, apps=spawn)
    s.start_apps()
    group = s._apps.pid

    s.stop_apps()

    with pytest.raises(ProcessLookupError):
        os.killpg(group, 0)
