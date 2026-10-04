"""make monitoring-dashboards — дашборды из infra/monitoring/dashboards в Grafana Cloud (3.3, K35).

Без --apply только печатает, что ушло бы (uid, заголовок, папка), и в сеть не ходит. С --apply —
папка «Соседи» (uid sosed) и каждый дашборд через HTTP API Grafana с overwrite: источник правды —
файлы в git, правки в UI перезапишутся. Адрес стека и токен service account (роль Editor) —
GRAFANA_URL и GRAFANA_SA_TOKEN из --env-file; токен не печатается.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from envfile import read

FOLDER_UID = "sosed"
FOLDER_TITLE = "Соседи"


def _request(base: str, token: str, method: str, path: str, body: object | None = None) -> object:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 — адрес из .env владельца
        return json.loads(resp.read() or b"null")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("dashboards", type=Path, nargs="+")
    args = parser.parse_args(argv)

    dashboards = [json.loads(p.read_text(encoding="utf-8")) for p in args.dashboards]
    for path, dash in zip(args.dashboards, dashboards, strict=True):
        mode = "push" if args.apply else "dry-run"
        print(f"{mode}: {dash['uid']} «{dash['title']}» → {FOLDER_TITLE} ({path.name})")
    if not args.apply:
        print("monitoring-dashboards: ничего не отправлено — APPLY=1, чтобы загрузить")
        return 0

    env = read(args.env_file)
    base, token = env.get("GRAFANA_URL", ""), env.get("GRAFANA_SA_TOKEN", "")
    if not base.startswith("https://") or not token:
        print("monitoring-dashboards: в .env нужны GRAFANA_URL (https://<стек>.grafana.net)")
        print("и GRAFANA_SA_TOKEN — make secret NAME=… TARGET=monitoring")
        return 2
    try:
        try:
            _request(base, token, "GET", f"/api/folders/{FOLDER_UID}")
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            folder = {"uid": FOLDER_UID, "title": FOLDER_TITLE}
            _request(base, token, "POST", "/api/folders", folder)
        for dash in dashboards:
            body = {
                "dashboard": {**dash, "id": None},
                "folderUid": FOLDER_UID,
                "overwrite": True,
                "message": "make monitoring-dashboards",
            }
            result = _request(base, token, "POST", "/api/dashboards/db", body)
            url = result.get("url", "") if isinstance(result, dict) else ""
            print(f"monitoring-dashboards: {dash['uid']} — OK {url}")
    except urllib.error.HTTPError as exc:
        # тело ответа Grafana — текст ошибки без токена
        detail = exc.read()[:300].decode(errors="replace")
        print(f"monitoring-dashboards: HTTP {exc.code} {exc.reason}: {detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
