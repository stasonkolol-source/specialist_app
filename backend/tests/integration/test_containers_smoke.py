"""Smoke тестового контура: наш PostGIS, Valkey и Garage (DEVELOPMENT_PLAN 0.5a)."""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from tests.plugins.containers import GarageInfo

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def probe_table(migrator_engine: AsyncEngine) -> AsyncIterator[str]:
    """Таблица для проверки отката: создаёт migrator (как миграции), app получает DML."""
    async with migrator_engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS test_harness"))
        await conn.execute(text("CREATE TABLE IF NOT EXISTS test_harness.probe (v int)"))
    yield "test_harness.probe"
    async with migrator_engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA test_harness CASCADE"))


async def _scalar(conn: AsyncConnection, sql: str) -> object:
    return (await conn.execute(text(sql))).scalar_one()


async def test_database_locale_trigram_and_postgis(db_connection: AsyncConnection) -> None:
    provider = await _scalar(
        db_connection,
        "SELECT datlocprovider::text || ':' || datlocale FROM pg_database "
        "WHERE datname = current_database()",
    )
    assert provider == "b:C.UTF-8"
    assert await _scalar(db_connection, "SELECT show_trgm('тест')::text") != "{}"
    assert str(await _scalar(db_connection, "SELECT postgis_lib_version()")).startswith("3.6")
    assert await _scalar(db_connection, "SELECT upper('ђорђе šđčćž')") == "ЂОРЂЕ ŠĐČĆŽ"


async def test_app_role_has_production_settings(db_connection: AsyncConnection) -> None:
    assert await _scalar(db_connection, "SELECT current_user") == "app"
    assert await _scalar(db_connection, "SHOW statement_timeout") == "5s"
    assert await _scalar(db_connection, "SHOW plan_cache_mode") == "force_custom_plan"
    assert await _scalar(db_connection, "SHOW max_parallel_workers_per_gather") == "0"
    can_create = await _scalar(
        db_connection, "SELECT has_database_privilege(current_database(), 'CREATE')"
    )
    assert can_create is False


async def test_changes_are_rolled_back_between_tests(
    probe_table: str, db_session: AsyncSession
) -> None:
    # commit в коде теста — это savepoint внешней транзакции, в конце теста всё откатится
    await db_session.execute(text(f"INSERT INTO {probe_table} VALUES (1)"))  # noqa: S608
    await db_session.commit()
    count = (await db_session.execute(text(f"SELECT count(*) FROM {probe_table}"))).scalar_one()  # noqa: S608
    assert count == 1


async def test_previous_test_left_nothing(probe_table: str, db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as conn:
        assert await _scalar(conn, f"SELECT count(*) FROM {probe_table}") == 0  # noqa: S608


async def test_app_role_cannot_create_temp_tables(db_connection: AsyncConnection) -> None:
    can_temp = await _scalar(
        db_connection, "SELECT has_database_privilege(current_database(), 'TEMP')"
    )
    assert can_temp is False


async def test_valkey_answers(valkey_url: str) -> None:
    client = Redis.from_url(valkey_url)
    try:
        assert await client.ping() is True
    finally:
        await client.aclose()


def test_garage_has_buckets(garage: GarageInfo) -> None:
    assert garage.endpoint_url.startswith("http://")
    assert garage.access_key_id.startswith("GK")
    assert set(garage.buckets) == {"incoming", "media", "private"}
