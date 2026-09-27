"""Правовые тексты в client-config и флаг техработ (DEVELOPMENT_PLAN 1.5a, S48, S49)."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.interfaces.http.middleware import MAINTENANCE_RETRY_AFTER
from app.platform.config.port import MAINTENANCE_FLAG
from app.platform.db.platform_tables import client_config, feature_flags
from app.platform.settings import Settings
from tests.plugins.http import http_client

pytestmark = pytest.mark.integration


@pytest.fixture
async def config_db(migrator_engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    """Вернуть версии документов и флаг техработ как было: их читают тесты identity и S49."""
    async with migrator_engine.connect() as conn:
        versions = (
            await conn.execute(
                select(client_config.c.value).where(client_config.c.key == "legal_versions")
            )
        ).scalar_one()
    yield migrator_engine
    async with migrator_engine.begin() as conn:
        await conn.execute(
            update(client_config)
            .where(client_config.c.key == "legal_versions")
            .values(value=versions)
        )
        await conn.execute(
            update(feature_flags)
            .where(feature_flags.c.key == MAINTENANCE_FLAG)
            .values(enabled=False)
        )


async def test_client_config_carries_texts_of_current_versions(settings: Settings) -> None:
    async with http_client(settings) as client:
        response = await client.get("/api/v1/client-config", headers={"accept-language": "sr"})
        body = response.json()
        assert body["legal_versions"] == {"terms": "draft-1", "privacy": "draft-1"}
        assert body["flags"][MAINTENANCE_FLAG] is False
        documents = body["legal_documents"]
        assert set(documents) == {"terms", "privacy"}
        for key, document in documents.items():
            assert document["version"] == body["legal_versions"][key]
            assert document["published_on"] == "2026-09-27"
            # перевода ещё нет (K41): язык запроса ответ не меняет, ru — всегда
            assert set(document["texts"]) == {"ru"}
        terms = documents["terms"]["texts"]["ru"]
        assert terms["title"] == "Правила площадки «Соседи»"
        assert terms["body"].startswith("Площадка «Соседи» помогает")
        assert "## 1. Кто может пользоваться" in terms["body"]
        # одинаковый для всех ответ: без Vary, тот же ETag для другого языка
        assert "vary" not in response.headers
        again = await client.get(
            "/api/v1/client-config",
            headers={"accept-language": "ru", "if-none-match": response.headers["etag"]},
        )
        assert again.status_code == 304


async def test_version_without_text_is_left_out(settings: Settings, config_db: AsyncEngine) -> None:
    """Версию включили в админке раньше, чем выложили текст: не отдаём чужую редакцию."""
    async with config_db.begin() as conn:
        await conn.execute(
            update(client_config)
            .where(client_config.c.key == "legal_versions")
            .values(value=text("""value || '{"terms": "draft-9"}'::jsonb"""))
        )
    async with http_client(settings) as client:
        body = (await client.get("/api/v1/client-config")).json()
        assert body["legal_versions"]["terms"] == "draft-9"
        assert set(body["legal_documents"]) == {"privacy"}


async def test_maintenance_closes_api_but_not_client_config(
    settings: Settings, config_db: AsyncEngine
) -> None:
    async with config_db.begin() as conn:
        await conn.execute(
            update(feature_flags)
            .where(feature_flags.c.key == MAINTENANCE_FLAG)
            .values(enabled=True)
        )
    async with http_client(settings) as client:
        closed = await client.get("/api/v1/cities", headers={"accept-language": "sr-Cyrl"})
        assert closed.status_code == 503
        assert closed.headers["content-type"] == "application/problem+json"
        assert closed.headers["retry-after"] == str(MAINTENANCE_RETRY_AFTER)
        body = closed.json()
        assert body["code"] == "maintenance"
        assert body["detail"].startswith("У току су технички радови")
        config = await client.get("/api/v1/client-config")
        assert config.status_code == 200
        assert config.json()["flags"][MAINTENANCE_FLAG] is True
        assert config.json()["legal_documents"]
        assert (await client.get("/up")).status_code == 200
