"""Контейнеры для интеграционных тестов (DEVELOPMENT_PLAN 0.5a, ADR-0020 §11).

PostgreSQL — наш образ с PostGIS и тем же bootstrap, что в dev и prod; Valkey; Garage.
Случайные порты, метка com.specialist.tests=true, dev-окружение не затрагивается.
Образ PostgreSQL собирает `make pg-image` (make test-int вызывает её сам).
"""

import os
import re
import secrets
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import ExecWaitStrategy

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"
PG_IMAGE = "specialist/postgres-postgis:18.6-3.6"
VALKEY_IMAGE = (
    "valkey/valkey:9.1@sha256:418652cfb58ef879d4978c33553735d7147016032d5aefaa14c828e611eb9dfd"
)
GARAGE_IMAGE = (
    "dxflrs/garage:v2.4.1@sha256:9c96caa2612d3411acc5b0e6701fb238dbfba33e533a6d7d3d811a4b12d0d020"
)
LABELS = {"com.specialist.tests": "true"}
DB_NAME = "specialist"
STARTUP_TIMEOUT = 180


@dataclass(frozen=True)
class PostgresInfo:
    host: str
    port: int
    passwords: dict[str, str]

    def dsn(self, role: str = "app", driver: str = "postgresql+psycopg") -> str:
        return f"{driver}://{role}:{self.passwords[role]}@{self.host}:{self.port}/{DB_NAME}"


@dataclass(frozen=True)
class GarageInfo:
    endpoint_url: str
    access_key_id: str
    secret_access_key: str
    buckets: tuple[str, ...]


def run_alembic(info: PostgresInfo, *args: str) -> subprocess.CompletedProcess[str]:
    """Alembic в отдельном процессе под ролью migrator (свой event loop, как в проде)."""
    env = {**os.environ, "DB_DSN": info.dsn("app"), "DB_MIGRATOR_DSN": info.dsn("migrator")}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _start_postgres() -> tuple[DockerContainer, PostgresInfo]:
    passwords = {
        role: secrets.token_urlsafe(16)
        for role in ("postgres", "app", "migrator", "readonly", "backup")
    }
    container = (
        DockerContainer(PG_IMAGE, **{"labels": LABELS})
        .with_envs(
            POSTGRES_USER="postgres",
            POSTGRES_PASSWORD=passwords["postgres"],
            POSTGRES_DB=DB_NAME,
            APP_DB_PASSWORD=passwords["app"],
            MIGRATOR_DB_PASSWORD=passwords["migrator"],
            READONLY_DB_PASSWORD=passwords["readonly"],
            BACKUP_DB_PASSWORD=passwords["backup"],
        )
        .with_command(
            "postgres -c shared_preload_libraries=pg_stat_statements -c fsync=off "
            "-c synchronous_commit=off -c full_page_writes=off"
        )
        .with_exposed_ports(5432)
        # До конца bootstrap сервер слушает только unix-сокет: TCP-вход роли app
        # означает, что initdb и bootstrap.sql отработали.
        .waiting_for(
            ExecWaitStrategy(
                [
                    "sh",
                    "-c",
                    f"PGPASSWORD='{passwords['app']}' psql -h 127.0.0.1 -U app -d {DB_NAME} "
                    "-Atc 'select 1'",
                ]
            ).with_startup_timeout(STARTUP_TIMEOUT)
        )
    )
    container.start()
    info = PostgresInfo(
        host=container.get_container_host_ip(),
        port=int(container.get_exposed_port(5432)),
        passwords=passwords,
    )
    return container, info


@pytest.fixture(scope="session")
def postgres() -> Iterator[PostgresInfo]:
    """Общая БД тестов — сразу с миграциями до head, как в проде."""
    container, info = _start_postgres()
    try:
        result = run_alembic(info, "upgrade", "head")
        assert result.returncode == 0, result.stderr
        yield info
    finally:
        container.stop()


@pytest.fixture(scope="module")
def fresh_postgres() -> Iterator[PostgresInfo]:
    """Чистая БД без миграций — для раунд-трипа миграций (он откатывает всё до base)."""
    container, info = _start_postgres()
    try:
        yield info
    finally:
        container.stop()


@pytest.fixture(scope="session")
def valkey_url() -> Iterator[str]:
    container = (
        DockerContainer(VALKEY_IMAGE, **{"labels": LABELS})
        .with_command("valkey-server --save '' --appendonly no")
        .with_exposed_ports(6379)
        .waiting_for(ExecWaitStrategy(["valkey-cli", "ping"]).with_startup_timeout(60))
    )
    container.start()
    try:
        host, port = container.get_container_host_ip(), container.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"
    finally:
        container.stop()


@pytest.fixture(scope="session")
def garage() -> Iterator[GarageInfo]:
    buckets = ("incoming", "media", "private")
    container = (
        DockerContainer(GARAGE_IMAGE, **{"labels": LABELS})
        .with_command("/garage server --single-node")
        .with_envs(
            GARAGE_RPC_SECRET=secrets.token_hex(32),
            GARAGE_ADMIN_TOKEN=secrets.token_urlsafe(16),
            GARAGE_METRICS_TOKEN=secrets.token_urlsafe(16),
        )
        .with_volume_mapping(str(REPO / "infra" / "compose" / "garage.toml"), "/etc/garage.toml")
        .with_exposed_ports(3900)
        .waiting_for(ExecWaitStrategy(["/garage", "status"]).with_startup_timeout(60))
    )
    container.start()
    try:
        out = container.exec(["/garage", "key", "create", "tests"]).output.decode()
        key_id = re.search(r"Key ID:\s*(\S+)", out)
        secret = re.search(r"Secret key:\s*(\S+)", out)
        assert key_id, out
        assert secret, out
        for bucket in buckets:
            container.exec(["/garage", "bucket", "create", bucket])
            container.exec(
                [
                    "/garage",
                    "bucket",
                    "allow",
                    "--read",
                    "--write",
                    "--owner",
                    bucket,
                    "--key",
                    "tests",
                ]
            )
        host, port = container.get_container_host_ip(), container.get_exposed_port(3900)
        yield GarageInfo(
            endpoint_url=f"http://{host}:{port}",
            access_key_id=key_id.group(1),
            secret_access_key=secret.group(1),
            buckets=buckets,
        )
    finally:
        container.stop()
