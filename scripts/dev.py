"""Весь dev-стенд одной командой (DEVELOPMENT_PLAN 0.22): `make dev`.

compose → миграции → сиды → туннели (адреса в .env, menu button) → honcho с Procfile.dev:
web, bot, worker, worker-media, tma. Ctrl+C останавливает процессы и туннели.
`make dev TUNNEL=0` — без туннелей (только локально).
"""

from __future__ import annotations


import os
import subprocess
import sys

from envfile import ROOT
from tunnel import open_tunnels, stop

HONCHO = ["uv", "tool", "run", "honcho", "start", "-f", "Procfile.dev", "-d", str(ROOT)]


def run(*command: str) -> None:
    subprocess.run(command, cwd=ROOT, check=True)  # noqa: S603


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]  # вывод сразу, даже в файл
    run("make", "up")
    run("make", "migrate")
    run("make", "seed")
    tunnels = open_tunnels() if os.environ.get("TUNNEL", "1") != "0" else []
    try:
        return subprocess.call(HONCHO, cwd=ROOT)  # noqa: S603
    except KeyboardInterrupt:
        return 0
    finally:
        stop(tunnels)
        sys.stdout.write("dev: stopped\n")


if __name__ == "__main__":
    raise SystemExit(main())
