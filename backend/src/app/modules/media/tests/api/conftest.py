"""API-тесты media: приложение целиком на PostgreSQL, Valkey и Garage из testcontainers.

Данные коммитятся, поэтому у каждого теста свои пользователи: квоты загрузок (Valkey) и
файлы не пересекаются между тестами.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from tests.plugins.containers import GarageInfo
from tests.plugins.http import HttpApp, bearer, http_app
from tests.plugins.identity import insert_user

from app.modules.media.http.router import router
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings


@pytest.fixture
def s3_settings(
    settings: Settings, garage: GarageInfo, monkeypatch: pytest.MonkeyPatch
) -> Settings:
    """Настройки теста плюс S3 на Garage: после `settings`, который чистит окружение."""
    monkeypatch.setenv("S3_ENDPOINT_URL", garage.endpoint_url)
    monkeypatch.setenv("S3_REGION", "garage")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", garage.access_key_id)
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", garage.secret_access_key)
    return Settings(env_file=None)


@dataclass
class Media:
    """Клиент API media от имени пользователя и прямой доступ к хранилищу."""

    app: HttpApp
    settings: Settings
    user_id: UserId
    headers: dict[str, str]

    async def start(self, **body: Any) -> httpx.Response:
        payload = {"purpose": "portfolio", "mime_type": "image/jpeg", "size_bytes": 2048} | body
        return await self.app.client.post(
            "/api/v1/media/uploads",
            json=payload,
            headers=self.headers | {"idempotency-key": f"k-{new_id().hex}"},
        )

    async def complete(
        self, media_id: str, parts: list[dict[str, Any]] | None = None
    ) -> httpx.Response:
        return await self.app.client.post(
            f"/api/v1/media/uploads/{media_id}/complete",
            json={"parts": parts or []},
            headers=self.headers,
        )

    async def get(self, media_id: str) -> httpx.Response:
        return await self.app.client.get(f"/api/v1/media/{media_id}", headers=self.headers)

    async def delete(self, media_id: str) -> httpx.Response:
        return await self.app.client.delete(f"/api/v1/media/{media_id}", headers=self.headers)

    async def processing_jobs(self, media_id: str) -> int:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.connect() as conn:
            return int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM procrastinate_jobs WHERE task_name ="
                            " 'media.process' AND args->'payload'->>'media_id' = :id"
                        ),
                        {"id": media_id},
                    )
                ).scalar_one()
            )

    async def other_user(self) -> Media:
        return await media_for(self.app, self.settings)


async def media_for(app: HttpApp, settings: Settings) -> Media:
    async with app.container() as request:
        session = await request.get(AsyncSession)
        user_id = await insert_user(session)
        await session.commit()
    return Media(app=app, settings=settings, user_id=user_id, headers=bearer(settings, user_id))


@pytest.fixture
async def web(s3_settings: Settings) -> AsyncIterator[HttpApp]:
    async with http_app(s3_settings, router) as app:
        yield app


@pytest.fixture
async def media(web: HttpApp, s3_settings: Settings) -> Media:
    return await media_for(web, s3_settings)


async def put(part: dict[str, Any], body: bytes) -> httpx.Response:
    """Загрузка в хранилище по presigned-ссылке — как это делает Mini App."""
    async with httpx.AsyncClient(timeout=60) as client:
        return await client.put(part["url"], content=body, headers=part["headers"])
