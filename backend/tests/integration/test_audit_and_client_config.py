"""Аудит только на добавление и client-config (DEVELOPMENT_PLAN 1.1)."""

from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from psycopg.errors import InsufficientPrivilege
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from app.platform.audit.port import ActorKind, AuditEntry
from app.platform.audit.sql import SqlAuditLog
from app.platform.config.cache import ClientConfigCache
from app.platform.db.platform_tables import audit_log, client_config, feature_flags
from app.platform.kernel.ids import new_id
from app.platform.settings import Settings
from tests.plugins.database import make_uow
from tests.plugins.http import http_client

pytestmark = pytest.mark.integration


async def _record(db_session: AsyncSession, procrastinate_app: object) -> UUID:
    entity = new_id()
    uow = make_uow(db_session, procrastinate_app)  # type: ignore[arg-type]
    async with uow:
        await SqlAuditLog(db_session, uow).record(
            AuditEntry(
                action="test.entry", actor_kind=ActorKind.STAFF, entity_type="t", entity_id=entity
            )
        )
    return entity


async def test_audit_is_append_only_for_app(
    db_session: AsyncSession, db_connection: AsyncConnection, procrastinate_app: object
) -> None:
    entity = await _record(db_session, procrastinate_app)
    rows = (
        await db_session.execute(select(audit_log.c.action).where(audit_log.c.entity_id == entity))
    ).all()
    assert [row.action for row in rows] == ["test.entry"]
    for statement in (
        update(audit_log).where(audit_log.c.entity_id == entity).values(action="forged"),
        audit_log.delete().where(audit_log.c.entity_id == entity),
    ):
        with pytest.raises(DBAPIError) as caught:
            async with db_connection.begin_nested():
                await db_connection.execute(statement)
        assert isinstance(caught.value.orig, InsufficientPrivilege)


async def test_audit_update_is_blocked_even_for_migrator(migrator_engine: AsyncEngine) -> None:
    async with migrator_engine.connect() as conn:
        transaction = await conn.begin()
        entity = new_id()
        await conn.execute(
            audit_log.insert().values(action="test.entry", actor_kind="system", entity_id=entity)
        )
        with pytest.raises(DBAPIError, match="append-only"):
            await conn.execute(
                update(audit_log).where(audit_log.c.entity_id == entity).values(action="x")
            )
        await transaction.rollback()


async def test_audit_needs_active_unit_of_work(
    db_session: AsyncSession, procrastinate_app: object
) -> None:
    uow = make_uow(db_session, procrastinate_app)  # type: ignore[arg-type]
    with pytest.raises(Exception, match="UnitOfWork"):
        await SqlAuditLog(db_session, uow).record(
            AuditEntry(action="x", actor_kind=ActorKind.SYSTEM)
        )


@pytest.fixture
async def restore_config(migrator_engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    yield migrator_engine
    async with migrator_engine.begin() as conn:
        await conn.execute(update(client_config).values(value=text("'{}'::jsonb")))
        await conn.execute(feature_flags.delete().where(feature_flags.c.key.like("test.%")))


async def test_client_config_serves_flags_with_etag(settings: Settings) -> None:
    async with http_client(settings) as client:
        response = await client.get("/api/v1/client-config")
        assert response.status_code == 200
        body = response.json()
        assert body["flags"]["goods.segment"] is True
        assert set(body) == {"min_versions", "flags", "legal_versions"}
        etag = response.headers["etag"]
        assert response.headers["cache-control"] == "public, max-age=60"
        cached = await client.get("/api/v1/client-config", headers={"if-none-match": etag})
        assert cached.status_code == 304
        assert cached.headers["etag"] == etag
        assert not cached.content
        other = await client.get("/api/v1/client-config", headers={"if-none-match": '"other"'})
        assert other.status_code == 200


async def test_min_versions_from_db_drive_426(
    settings: Settings, restore_config: AsyncEngine
) -> None:
    async with restore_config.begin() as conn:
        await conn.execute(
            update(client_config)
            .where(client_config.c.key == "min_versions")
            .values(value=text("""'{"tma": "2.0.0"}'::jsonb"""))
        )
    async with http_client(settings) as client:
        body = (await client.get("/api/v1/client-config")).json()
        assert body["min_versions"] == {"tma": "2.0.0"}
        old = await client.get("/api/v1/client-config", headers={"x-client": "tma/1.9.9"})
        assert old.status_code == 426
        assert old.json()["min_version"] == "2.0.0"
        assert (
            await client.get("/api/v1/client-config", headers={"x-client": "tma/2.0"})
        ).status_code == 200


async def test_cache_refreshes_after_ttl(
    settings: Settings, restore_config: AsyncEngine, db_engine: AsyncEngine
) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    now = [0.0]
    cache = ClientConfigCache(async_sessionmaker(db_engine), monotonic=lambda: now[0])
    assert not await cache.is_enabled("test.hidden")
    async with restore_config.begin() as conn:
        await conn.execute(
            feature_flags.insert().values(
                key="test.hidden", enabled=True, value={"w": 2}, public=False
            )
        )
    assert not await cache.is_enabled("test.hidden")  # ещё в кэше
    now[0] += 31
    assert await cache.is_enabled("test.hidden")
    assert await cache.value("test.hidden") == {"w": 2}
    assert "test.hidden" not in (await cache.get()).public_flags()
