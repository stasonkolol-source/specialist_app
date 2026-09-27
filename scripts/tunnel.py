"""Quick tunnel cloudflared для dev (DEVELOPMENT_PLAN 0.22, K6 вариант B).

    make tunnel     — поднять туннели, прописать адреса, обновить menu button; Ctrl+C — стоп
    make dev        — то же вместе со всеми процессами (scripts/dev.py)

Два туннеля: Mini App (Vite :5173, он же проксирует /api на :8000 — один origin, правило
Bot API 10.2) и Garage (:59100) — адрес для presigned-ссылок загрузки с телефона (0.24).
Адреса *.trycloudflare.com меняются при каждом запуске, поэтому скрипт каждый раз:
- пишет TELEGRAM_MINI_APP_URL и S3_PUBLIC_ENDPOINT_URL в backend/.env;
- пишет TMA_ALLOWED_HOSTS и TMA_HMR_HOST в apps/tma/.env (Vite: хост туннеля и HMR по wss:443),
  TMA_STORAGE_ORIGINS — адрес туннеля Garage для CSP (PUT по presigned-ссылкам);
- вызывает `cli set-menu-button` — кнопка меню бота открывает новый адрес.
"""

from __future__ import annotations


import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from envfile import ROOT, update

URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
LOGS = ROOT / ".tunnel-logs"
APP_PORT = 5173
GARAGE_PORT = 59100


@dataclass
class Tunnel:
    name: str
    port: int
    process: subprocess.Popen[str]
    url: str

    @property
    def host(self) -> str:
        return self.url.removeprefix("https://")


def start(name: str, port: int, timeout: float = 90.0) -> Tunnel:
    LOGS.mkdir(exist_ok=True)
    process = subprocess.Popen(  # noqa: S603 — фиксированная команда
        ["cloudflared", "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],  # noqa: S607
        stderr=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        text=True,
    )
    assert process.stderr is not None
    log = (LOGS / f"{name}.log").open("w", encoding="utf-8")
    found: list[str] = []
    ready = threading.Event()

    def drain() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            log.write(line)
            log.flush()
            if not found and (match := URL.search(line)):
                found.append(match.group(0))
                ready.set()

    threading.Thread(target=drain, daemon=True).start()
    if not ready.wait(timeout):
        process.terminate()
        raise SystemExit(f"tunnel {name}: no URL in {timeout:.0f}s, see {LOGS / (name + '.log')}")
    return Tunnel(name=name, port=port, process=process, url=found[0])


def configure(app: Tunnel, garage: Tunnel | None) -> None:
    backend = {"TELEGRAM_MINI_APP_URL": app.url}
    if garage is not None:
        backend["S3_PUBLIC_ENDPOINT_URL"] = garage.url
    changed = update(ROOT / "backend" / ".env", backend, overwrite=True)
    tma_env = ROOT / "apps" / "tma" / ".env"
    tma = {"TMA_ALLOWED_HOSTS": app.host, "TMA_HMR_HOST": app.host}
    if garage is not None:
        tma["TMA_STORAGE_ORIGINS"] = garage.url  # CSP: PUT по presigned-ссылкам (0.24)
    changed += update(tma_env, tma, overwrite=True)
    sys.stdout.write(f"env: updated {', '.join(changed) or 'nothing'}\n")
    result = subprocess.run(  # noqa: S603
        ["uv", "run", "python", "-m", "app.entrypoints.cli", "set-menu-button", app.url],  # noqa: S607
        cwd=ROOT / "backend",
        check=False,
        capture_output=True,
        text=True,
    )
    sys.stdout.write((result.stdout or result.stderr).strip() + "\n")


def open_tunnels(*, garage: bool = True) -> list[Tunnel]:
    app = start("app", APP_PORT)
    s3 = start("garage", GARAGE_PORT) if garage else None
    configure(app, s3)
    sys.stdout.write(
        f"\n  Mini App: {app.url}\n"
        + (f"  Garage:   {s3.url}\n" if s3 else "")
        + "\n  Если в BotFather включён Main Mini App (K5), обновите там адрес на Mini App выше.\n\n"
    )
    return [t for t in (app, s3) if t is not None]


def stop(tunnels: list[Tunnel]) -> None:
    for tunnel in tunnels:
        tunnel.process.terminate()
    for tunnel in tunnels:
        try:
            tunnel.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            tunnel.process.kill()


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]  # вывод сразу, даже в файл
    tunnels = open_tunnels(garage="--no-garage" not in sys.argv)
    sys.stdout.write("Туннели работают; перезапустите bot и tma, если они уже запущены. Ctrl+C — стоп.\n")
    try:
        while all(t.process.poll() is None for t in tunnels):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop(tunnels)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
