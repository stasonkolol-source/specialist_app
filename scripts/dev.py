"""Весь dev-стенд одной командой (DEVELOPMENT_PLAN 0.22): `make dev`.

compose → миграции → сиды → туннели (адреса в .env, menu button) → honcho с Procfile.dev:
web, bot, worker, worker-media, tma. Ctrl+C или SIGTERM останавливает процессы и туннели.
`make dev TUNNEL=0` — без туннелей (только локально).
`make dev TMA=dev` — Mini App из dev-сервера Vite с HMR вместо сборки (Procfile.dev).

Стенд чинит себя сам (quick tunnel живёт, пока жива связь):
- Cloudflare удаляет quick tunnel, если связь пропала надолго (сон Мака): адрес перестаёт
  резолвиться или отдаёт 530. Раз в минуту скрипт проверяет адреса туннелей; три провала
  подряд при живом интернете — новые туннели (адреса в .env, menu button) и перезапуск
  процессов, чтобы они прочитали новые адреса. Кнопки «Открыть» в старых сообщениях бота
  после этого ведут на мёртвый адрес — постоянный адрес даёт только 0.28.
- Упавшие процессы поднимаются заново: бот выходит, когда Telegram не отвечает (VPN, сон Мака,
  обрыв сети), а honcho за ним гасит весь стенд. Перезапуск — с паузой 10 с, 30 с, 1, 2, 5 мин;
  без интернета ждём связь и попытки не тратим. Больше MAX_CRASHES падений за CRASH_WINDOW —
  это уже не сеть, а ошибка в коде: стенд останавливается, как раньше. Код 0 (honcho вышел сам,
  без сбоя) — тоже остановка.
- `make dev-restart` (SIGUSR1) перезапускает только процессы — после merge, когда бот и
  воркеры должны подхватить новый код; туннели и их адреса остаются.
- `make dev-bg` запускает стенд в фоне, в своей сессии процессов: он переживает закрытие
  терминала, IDE и агента. Лог — `.tunnel-logs/dev.log`, остановка — `make dev-stop`.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from envfile import ROOT
from tunnel import LOGS, Tunnel, open_tunnels, stop

HONCHO = ["uv", "tool", "run", "honcho", "start", "-f", "Procfile.dev", "-d", str(ROOT)]
PID_FILE = LOGS / "dev.pid"
LOG_FILE = LOGS / "dev.log"

CHECK_EVERY = 60.0
FAILURES_BEFORE_RECREATE = 3
APPS_STOP_TIMEOUT = 20.0
RESTART_DELAYS = (10.0, 30.0, 60.0, 120.0, 300.0)
"""Паузы перед перезапуском упавших процессов: первое падение, второе, … (дальше — последняя)."""
CRASH_WINDOW = 30 * 60.0
MAX_CRASHES = 5
OFFLINE_RECHECK = 30.0
ONLINE_PROBE = "https://www.cloudflare.com/cdn-cgi/trace"
TUNNEL_DOWN = 530
"""Ответ Cloudflare «туннель не подключён» (ошибки 1033, 1016): процесс cloudflared жив,
но Cloudflare туннель уже не знает."""


def log(message: str) -> None:
    sys.stdout.write(f"{datetime.now():%H:%M:%S} dev: {message}\n")


def reachable(url: str, timeout: float = 10.0) -> bool:
    """Отвечает ли адрес хоть чем-то, кроме «туннель не подключён».

    Любой HTTP-ответ, даже 403 от Garage или 502 от перезапускающегося Vite, значит, что
    туннель жив: Cloudflare знает адрес и держит соединение с cloudflared.
    """
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "sosed-dev-probe"})
    try:
        with urllib.request.urlopen(request, timeout=timeout):  # noqa: S310 — https-адрес
            return True
    except urllib.error.HTTPError as exc:
        return exc.code != TUNNEL_DOWN
    except (urllib.error.URLError, OSError):
        return False


class Stop(Exception):
    """SIGTERM или закрытый терминал (SIGHUP): остановить стенд так же, как Ctrl+C."""


class Stand:
    """Процессы стенда (honcho) и туннели; зависимости подменяются в тестах."""

    def __init__(
        self,
        *,
        tunnels: bool,
        probe: Callable[[str], bool] = reachable,
        opener: Callable[[], list[Tunnel]] = open_tunnels,
        closer: Callable[[list[Tunnel]], None] = stop,
        apps: Callable[[], subprocess.Popen[bytes]] | None = None,
    ) -> None:
        self.with_tunnels = tunnels
        self.tunnels: list[Tunnel] = []
        self.failures = 0
        self.restart_requested = False
        self._probe, self._opener, self._closer = probe, opener, closer
        self._spawn = apps or self._spawn_honcho
        self._apps: subprocess.Popen[bytes] | None = None

    # --- процессы -------------------------------------------------------------------------

    @staticmethod
    def _spawn_honcho() -> subprocess.Popen[bytes]:
        # своя группа процессов: остановка гасит honcho и всех его детей разом,
        # а Ctrl+C в терминале приходит только сюда — порядок остановки решает dev.py
        return subprocess.Popen(HONCHO, cwd=ROOT, start_new_session=True)  # noqa: S603

    def start_apps(self) -> None:
        self._apps = self._spawn()

    def stop_apps(self) -> None:
        """Остановить honcho и всё его дерево: web, bot, воркеры, vite.

        honcho запускает каждый процесс в своей сессии (start_new_session), поэтому сигнал
        группе honcho до них не доходит, а упавший honcho оставил бы их сиротами со старым
        кодом и занятыми портами. Дерево собирается по ppid до остановки; SIGTERM — всем,
        кто не вышел за APPS_STOP_TIMEOUT, получает SIGKILL."""
        apps, self._apps = self._apps, None
        if apps is None:
            return
        tree = [apps.pid, *_descendants(apps.pid)]
        for pid in tree:
            _signal(pid, signal.SIGTERM)
        deadline = time.monotonic() + APPS_STOP_TIMEOUT
        while time.monotonic() < deadline and any(_alive(pid) for pid in tree):
            apps.poll()  # забрать лидера, иначе он останется зомби
            time.sleep(0.2)
        for pid in tree:
            if _alive(pid):
                _signal(pid, signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            apps.wait(5)

    def restart_apps(self, reason: str) -> None:
        log(f"restart apps: {reason}")
        self.stop_apps()
        self.start_apps()

    def apps_exit_code(self) -> int | None:
        return self._apps.poll() if self._apps is not None else None

    # --- туннели --------------------------------------------------------------------------

    def open_tunnels(self) -> bool:
        try:
            self.tunnels = self._opener()
        except SystemExit as exc:  # cloudflared не выдал адрес: нет связи или лимит Cloudflare
            log(f"tunnels not ready: {exc}")
            self.tunnels = []
            return False
        return True

    def check_tunnels(self) -> None:
        """Проверка раз в CHECK_EVERY: мёртвые туннели → новые адреса и перезапуск процессов."""
        if not self.with_tunnels:
            return
        dead = [
            t.name for t in self.tunnels if t.process.poll() is not None or not self._probe(t.url)
        ]
        if self.tunnels and not dead:
            self.failures = 0
            return
        if not self._probe(ONLINE_PROBE):
            log("offline: tunnel check postponed")
            return
        if self.tunnels:
            self.failures += 1
            names = ", ".join(dead)
            log(f"tunnel {names} unreachable ({self.failures}/{FAILURES_BEFORE_RECREATE})")
            if self.failures < FAILURES_BEFORE_RECREATE:
                return
            log("recreating tunnels")
            self._closer(self.tunnels)
            self.tunnels = []
        self.failures = 0
        if self.open_tunnels():
            self.restart_apps("new tunnel addresses")

    def close_tunnels(self) -> None:
        self._closer(self.tunnels)
        self.tunnels = []

    # --- цикл -----------------------------------------------------------------------------

    def run(
        self,
        *,
        tick: float = 1.0,
        check_every: float = CHECK_EVERY,
        restart_delays: tuple[float, ...] = RESTART_DELAYS,
        crash_window: float = CRASH_WINDOW,
        max_crashes: int = MAX_CRASHES,
    ) -> int:
        if self.with_tunnels and not self.open_tunnels():
            raise SystemExit("dev: no tunnels — check the network or run `make dev TUNNEL=0`")
        self.start_apps()
        next_check = time.monotonic() + check_every
        crashes: list[float] = []
        restart_at: float | None = None  # процессы упали — когда поднимать их снова
        while True:
            time.sleep(tick)
            if self.restart_requested:
                self.restart_requested = False
                restart_at = None
                try:
                    self.restart_apps("make dev-restart")
                except Exception:  # noqa: BLE001 — стенд живёт, ошибка — в лог
                    log("restart failed:\n" + traceback.format_exc())
            if restart_at is not None:
                if time.monotonic() < restart_at:
                    continue
                if not self._probe(ONLINE_PROBE):
                    # без сети бот упадёт снова: ждём связь, попытки не тратим
                    log("offline: apps restart postponed")
                    restart_at = time.monotonic() + OFFLINE_RECHECK
                    continue
                restart_at = None
                log("restart apps after crash")
                self.start_apps()
                continue
            code = self.apps_exit_code()
            if code is not None:
                if code == 0:
                    log("apps exited with code 0")
                    return code
                now = time.monotonic()
                crashes = [at for at in crashes if now - at < crash_window] + [now]
                if len(crashes) > max_crashes:
                    log(
                        f"apps exited with code {code}: {len(crashes)} crashes in "
                        f"{crash_window / 60:.0f} min — stopping"
                    )
                    return code
                delay = restart_delays[min(len(crashes), len(restart_delays)) - 1]
                log(
                    f"apps exited with code {code}; restart in {delay:.0f}s "
                    f"({len(crashes)}/{max_crashes})"
                )
                self.stop_apps()  # добить осиротевших детей honcho и освободить порты
                restart_at = now + delay
                continue
            if time.monotonic() >= next_check:
                try:
                    self.check_tunnels()
                except Exception:  # noqa: BLE001 — сбой проверки не должен ронять стенд
                    log("tunnel check failed:\n" + traceback.format_exc())
                next_check = time.monotonic() + check_every


def _descendants(root: int) -> list[int]:
    """Все потомки процесса по ppid (`ps`), в том числе в других сессиях и группах."""
    listing = subprocess.run(  # noqa: S603 — фиксированная команда
        ["ps", "-axo", "pid=,ppid="],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    children: dict[int, list[int]] = {}
    for line in listing.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0].isdigit() and fields[1].isdigit():
            children.setdefault(int(fields[1]), []).append(int(fields[0]))
    found: list[int] = []
    stack = [root]
    while stack:
        for child in children.get(stack.pop(), []):
            found.append(child)
            stack.append(child)
    return found


def _alive(pid: int) -> bool:
    """Процесс есть и его можно остановить. PermissionError — на macOS так отвечают за
    зомби (и за чужие процессы): останавливать там нечего."""
    if pid <= 0:  # kill(0 или -1) — сигнал всей группе или всем процессам пользователя
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _signal(pid: int, sig: signal.Signals) -> None:
    if pid <= 0:  # kill(-1) погасил бы все процессы пользователя, kill(0) — свою группу
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.kill(pid, sig)


# --- команды make ---------------------------------------------------------------------------


def running_pid() -> int | None:
    """Pid работающего стенда из PID_FILE или None (файла нет, процесс умер)."""
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)
    except (FileNotFoundError, ValueError, ProcessLookupError):
        return None
    except PermissionError:
        return pid  # процесс есть, но чужой пользователь — считаем занятым
    return pid


def background() -> int:
    """`make dev-bg`: тот же стенд, но в своей сессии процессов, вывод — в LOG_FILE."""
    if (pid := running_pid()) is not None:
        sys.stdout.write(f"dev: already running (pid {pid}); make dev-restart | make dev-stop\n")
        return 1
    LOGS.mkdir(exist_ok=True)
    with LOG_FILE.open("ab") as out:
        child = subprocess.Popen(  # noqa: S603 — тот же интерпретатор и скрипт
            [sys.executable, str(Path(__file__).resolve())],
            cwd=Path(__file__).resolve().parent,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    sys.stdout.write(f"dev: started in background (pid {child.pid}), log {LOG_FILE}\n")
    return 0


def send(sig: signal.Signals, action: str) -> int:
    """`make dev-restart` (SIGUSR1) и `make dev-stop` (SIGTERM) для стенда из PID_FILE."""
    pid = running_pid()
    if pid is None:
        sys.stdout.write("dev: not running\n")
        return 1
    os.kill(pid, sig)
    sys.stdout.write(f"dev: {action} (pid {pid})\n")
    if sig is signal.SIGTERM:
        deadline = time.monotonic() + APPS_STOP_TIMEOUT + 15
        while running_pid() is not None and time.monotonic() < deadline:
            time.sleep(0.5)
    return 0


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]  # вывод сразу, даже в файл
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command == "--background":
        return background()
    if command == "--restart":
        return send(signal.SIGUSR1, "restarting apps")
    if command == "--stop":
        return send(signal.SIGTERM, "stopping")
    if (pid := running_pid()) is not None and pid != os.getpid():
        sys.stdout.write(f"dev: already running (pid {pid}); make dev-restart | make dev-stop\n")
        return 1

    subprocess.run(["make", "up"], cwd=ROOT, check=True)  # noqa: S603, S607
    subprocess.run(["make", "migrate"], cwd=ROOT, check=True)  # noqa: S603, S607
    subprocess.run(["make", "seed"], cwd=ROOT, check=True)  # noqa: S603, S607

    stand = Stand(tunnels=os.environ.get("TUNNEL", "1") != "0")

    def on_restart(_signum: int, _frame: object) -> None:
        stand.restart_requested = True

    def on_stop(_signum: int, _frame: object) -> None:
        raise Stop

    signal.signal(signal.SIGUSR1, on_restart)
    signal.signal(signal.SIGTERM, on_stop)
    signal.signal(signal.SIGHUP, on_stop)  # закрыли терминал с `make dev`
    LOGS.mkdir(exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    try:
        return stand.run()
    except (KeyboardInterrupt, Stop):
        return 0
    finally:
        stand.stop_apps()
        stand.close_tunnels()
        PID_FILE.unlink(missing_ok=True)
        log("stopped")


if __name__ == "__main__":
    raise SystemExit(main())
