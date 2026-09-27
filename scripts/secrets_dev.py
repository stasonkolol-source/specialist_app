"""make secrets-dev: dev-пароли и секреты в .env без вывода значений (DEVELOPMENT_PLAN 0.3, 0.4).

Повторный запуск ничего не меняет: существующие значения сохраняются.
"""

from __future__ import annotations

import secrets
import sys

from envfile import ROOT, read, update

COMPOSE_ENV = ROOT / "infra" / "compose" / ".env"
BACKEND_ENV = ROOT / "backend" / ".env"

PG_HOST, PG_PORT, PG_DB = "127.0.0.1", 55442, "specialist"


def token(nbytes: int = 24) -> str:
    return secrets.token_urlsafe(nbytes)


def main() -> int:
    compose_new = {
        "POSTGRES_SUPERUSER_PASSWORD": token(),
        "APP_DB_PASSWORD": token(),
        "MIGRATOR_DB_PASSWORD": token(),
        "READONLY_DB_PASSWORD": token(),
        "BACKUP_DB_PASSWORD": token(),
        "GARAGE_RPC_SECRET": secrets.token_hex(32),
        "GARAGE_ADMIN_TOKEN": token(),
        "GARAGE_METRICS_TOKEN": token(),
    }
    changed_compose = update(COMPOSE_ENV, compose_new)
    compose = read(COMPOSE_ENV)

    def dsn(role: str, password_key: str) -> str:
        return f"postgresql+psycopg://{role}:{compose[password_key]}@{PG_HOST}:{PG_PORT}/{PG_DB}"

    backend_new = {
        "DB_DSN": dsn("app", "APP_DB_PASSWORD"),
        "DB_MIGRATOR_DSN": dsn("migrator", "MIGRATOR_DB_PASSWORD"),
        "VALKEY_URL": "redis://127.0.0.1:56379/0",
    }
    changed_backend = update(BACKEND_ENV, backend_new)

    for path, changed in ((COMPOSE_ENV, changed_compose), (BACKEND_ENV, changed_backend)):
        rel = path.relative_to(ROOT)
        status = f"added {', '.join(changed)}" if changed else "unchanged"
        sys.stdout.write(f"{rel}: {status}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
