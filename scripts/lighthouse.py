"""Lighthouse в Docker с мобильным профилем (DEVELOPMENT_PLAN 8.2, 4.8).

    make lighthouse URL=https://stage-app.<domain>
    make lighthouse URL=http://host.docker.internal:5173   — стенд на Маке (make dev-bg)

Профиль — мобильный по умолчанию Lighthouse: экран Moto G Power (412×823), медленный 4G (RTT 150 мс,
1,6 Мбит/с) и процессор ×4, троттлинг simulate; только категория «Производительность». CLI
закреплённой версии ставит npx в образ Playwright, закреплённый для e2e (Chromium — оттуда же):
в репозитории новых npm-зависимостей нет, пакет кэшируется в томе Docker `sosed-lighthouse-npm`.
Отчёты HTML и JSON — в .lighthouse/ (не в git). Печатает FCP, LCP, TBT, CLS и вес страницы;
LCP больше бюджета (2,5 с — холодный старт, 4.8) — код выхода 1.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / ".lighthouse"
VERSION = "13.5.0"
LCP_BUDGET_MS = 2500
CACHE_VOLUME = "sosed-lighthouse-npm"

# Внутри контейнера. vite preview пускает только localhost и IP-адреса (allowedHosts), поэтому стенд
# на Маке открываем по IP хоста Docker. Путь к Chromium в образе зависит от архитектуры.
RUN = r"""
set -e
url="$URL"
case "$url" in
  *://host.docker.internal*)
    ip=$(getent ahostsv4 host.docker.internal | awk 'NR == 1 {print $1}')
    url=$(printf '%s' "$url" | sed "s#://host.docker.internal#://$ip#") ;;
esac
CHROME_PATH=$(ls -d /ms-playwright/chromium-*/chrome-linux*/chrome | head -1)
export CHROME_PATH
npx --yes "lighthouse@$VERSION" "$url" --quiet --only-categories=performance \
  --form-factor=mobile --throttling-method=simulate \
  --chrome-flags="--headless=new --no-sandbox" \
  --output=json --output=html --output-path="/out/$NAME"
"""


def _seconds(ms: float) -> str:
    return f"{ms / 1000:.2f} с".replace(".", ",")


METRICS = (
    ("first-contentful-paint", "FCP", _seconds),
    ("largest-contentful-paint", "LCP", _seconds),
    ("total-blocking-time", "TBT", lambda ms: f"{ms:.0f} мс"),
    ("cumulative-layout-shift", "CLS", lambda value: f"{value:.3f}".replace(".", ",")),
    ("total-byte-weight", "Вес", lambda size: f"{size / 1024:.0f} KiB"),
)


def run(url: str, image: str, name: str) -> int:
    command = [
        "docker", "run", "--rm", "--init", "--ipc=host",
        "--add-host", "host.docker.internal:host-gateway",
        "-v", f"{OUT}:/out", "-v", f"{CACHE_VOLUME}:/root/.npm",
        "-e", f"URL={url}", "-e", f"NAME={name}", "-e", f"VERSION={VERSION}",
        "-e", "NPM_CONFIG_UPDATE_NOTIFIER=false",
        image, "sh", "-c", RUN,
    ]  # fmt: skip
    return subprocess.run(command, check=False).returncode


def summary(report: dict[str, Any], budget_ms: int) -> int:
    """Ключевые метрики; 1 — LCP нет (страница не открылась) или он больше бюджета."""
    if error := report.get("runtimeError"):
        print(f"lighthouse: страница не открылась: {error.get('code')} {error.get('message')}")
        return 1
    audits = report["audits"]
    score = report["categories"]["performance"]["score"]
    version, url = report["lighthouseVersion"], report["finalDisplayedUrl"]
    print(f"Lighthouse {version}, мобильный профиль: {url}")
    if score is not None:
        print(f"  Производительность  {score * 100:.0f}")
    for key, label, fmt in METRICS:
        value = audits[key].get("numericValue")
        print(f"  {label:<18}  {fmt(value) if value is not None else '—'}")
    lcp = audits["largest-contentful-paint"].get("numericValue")
    if lcp is None:
        print("lighthouse: LCP не измерен")
        return 1
    if lcp > budget_ms:
        print(f"lighthouse: LCP {_seconds(lcp)} больше бюджета {_seconds(budget_ms)}")
        return 1
    print(f"LCP в бюджете {_seconds(budget_ms)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("url")
    parser.add_argument("--image", required=True, help="образ Playwright (PLAYWRIGHT_IMAGE)")
    parser.add_argument("--lcp-budget-ms", type=int, default=LCP_BUDGET_MS)
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    name = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    if run(args.url, args.image, name) != 0:
        print("lighthouse: прогон не удался", file=sys.stderr)
        return 1
    report = json.loads((OUT / f"{name}.report.json").read_text(encoding="utf-8"))
    code = summary(report, args.lcp_budget_ms)
    print(f"Отчёт: {(OUT / f'{name}.report.html').relative_to(ROOT)}")
    return code


if __name__ == "__main__":
    sys.exit(main())
