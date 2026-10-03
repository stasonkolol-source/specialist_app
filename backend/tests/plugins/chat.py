"""Переписка в API-тестах (DEVELOPMENT_PLAN 6.3a, 6.3b): пользователи, заявка и отклик, диалоги и
сообщения через HTTP. Данные коммитятся: тест сам убирает свои задачи из очереди (`users`)."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings
from tests.plugins.http import HttpApp, bearer
from tests.plugins.identity import accept_rules, insert_user

API = "/api/v1"


class Chat:
    def __init__(self, app: HttpApp, settings: Settings) -> None:
        self.app, self.settings = app, settings
        self.users: list[UserId] = []

    async def scalar(self, sql: str, **params: object) -> Any:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).scalar()

    async def rows(self, sql: str, **params: object) -> list[tuple[Any, ...]]:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.connect() as conn:
            return [tuple(row) for row in (await conn.execute(text(sql), params)).all()]

    async def execute(self, sql: str, **params: object) -> None:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.begin() as conn:
            await conn.execute(text(sql), params)

    async def user(self, *, telegram_id: int | None = None) -> UserId:
        async with self.app.container() as request:
            session = await request.get(AsyncSession)
            user_id = await insert_user(session, telegram_id=telegram_id)
            await accept_rules(session, user_id)
        self.users.append(user_id)
        return user_id

    async def job(self, client_id: UserId) -> UUID:
        """Опубликованная заявка: модерация заявки тесту не нужна."""
        job_id = new_id()
        category = await self.scalar(
            "SELECT min(id) FROM catalog.categories WHERE is_active AND jobs_enabled"
            " AND risk_level = 0 AND parent_id IS NOT NULL"
        )
        path = await self.scalar("SELECT path FROM catalog.categories WHERE id = :id", id=category)
        now = datetime.now(UTC)
        await self.execute(
            "INSERT INTO jobs.jobs (id, client_id, status, title, description, content_lang,"
            " category_id, category_path, urgency, budget_type, budget_min, city_id,"
            " address_private, point_exact, published_at, expires_at, version)"
            " VALUES (:id, :client, 'published', 'Повесить люстру', 'Люстра на пять рожков',"
            " 'ru', :category, :path, 'this_week', 'fixed', 500000,"
            " (SELECT id FROM geo.cities WHERE slug = 'novi-sad'), 'бул. Цара Лазара, 56',"
            " ST_GeogFromText('SRID=4326;POINT(19.84 45.25)'), :published, :expires, 1)",
            id=job_id,
            client=client_id,
            category=category,
            path=list(path),
            published=now - timedelta(minutes=30),
            expires=now + timedelta(days=7),
        )
        return job_id

    async def response(self, performer: UserId, job_id: UUID, message: str | None = None) -> str:
        """Отклик, уже прошедший проверку: клиент его видит."""
        body = {
            "message": message or f"Здравствуйте! Могу сегодня в 19:00. {new_id().hex[-8:]}",
            "price_type": "fixed",
            "price_amount": 350_000,
            "availability_note": "Сегодня, 19:00",
        }
        headers = self.headers(performer) | {"Idempotency-Key": new_id().hex}
        reply = await self.app.client.post(
            f"{API}/jobs/{job_id}/responses", json=body, headers=headers
        )
        assert reply.status_code == 201, reply.text
        response_id: str = reply.json()["id"]
        await self.execute(
            "UPDATE jobs.responses SET review = 'clear' WHERE id = :id", id=UUID(response_id)
        )
        return response_id

    async def pair(self) -> tuple[UserId, UserId, str]:
        """Клиент, исполнитель и отклик исполнителя на заявку клиента."""
        client, performer = await self.user(), await self.user()
        return client, performer, await self.response(performer, await self.job(client))

    def headers(self, user_id: UserId, *, trust_level: int = 0) -> dict[str, str]:
        return bearer(self.settings, user_id, trust_level=trust_level)

    async def post(self, user: UserId, path: str, body: Any = None) -> httpx.Response:
        return await self.app.client.post(f"{API}{path}", json=body, headers=self.headers(user))

    async def get(self, user: UserId, path: str, **headers: str) -> httpx.Response:
        return await self.app.client.get(f"{API}{path}", headers=self.headers(user) | headers)

    async def start(self, user: UserId, **target: str) -> str:
        reply = await self.post(user, "/conversations", target)
        assert reply.status_code in (200, 201), reply.text
        conversation_id: str = reply.json()["id"]
        return conversation_id

    async def send(self, user: UserId, conversation_id: str, body: str, **extra: str) -> Any:
        reply = await self.post(
            user, f"/conversations/{conversation_id}/messages", {"body": body, **extra}
        )
        assert reply.status_code == 201, reply.text
        return reply.json()

    async def messages(self, user: UserId, conversation_id: str, **query: str | int) -> Any:
        reply = await self.app.client.get(
            f"{API}/conversations/{conversation_id}/messages",
            params=query,
            headers=self.headers(user),
        )
        assert reply.status_code == 200, reply.text
        return reply.json()

    async def mine(self, user: UserId) -> dict[str, Any]:
        reply = await self.get(user, "/conversations")
        assert reply.status_code == 200, reply.text
        return {item["id"]: item for item in reply.json()["items"]}
