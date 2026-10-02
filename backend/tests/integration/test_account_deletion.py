"""Удаление аккаунта сквозь модули (DEVELOPMENT_PLAN 2.12a, ARCHITECTURE §7.10).

Специалист с профилем, прайсом, работой портфолио, фото профиля, каналом уведомлений,
атрибуцией, избранным и заявкой просит удалить аккаунт (S45). Когда срок прошёл,
`identity.process_deletions` исполняет запрос, а подписчики UserDeleted и ProfileDeleted удаляют
своё — задачи выполняются так, как их выполнил бы воркер. Сессия больше не работает, хэш
Telegram ID записан.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._wiring import module_routers
from app.modules.identity.application.use_cases.process_deletions import (
    ProcessDeletions,
    ProcessDeletionsCommand,
)
from app.modules.identity.di import DEV_HASH_KEY
from app.modules.identity.domain.deletion import HashKind, identity_hash
from app.platform.kernel.ids import new_id
from app.platform.settings import Settings
from tests.plugins.http import HttpApp, http_app
from tests.plugins.identity import (
    accept_rules,
    bearer,
    login,
    new_telegram_id,
    signed_init_data,
    user_id_of,
)
from tests.plugins.queue import run_queued

pytestmark = pytest.mark.integration

API = "/api/v1"


@pytest.fixture
async def app(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[HttpApp]:
    # свой адрес клиента: лимит входов считается по IP, а API-тесты входят часто
    ip = f"10.{new_id().int % 250}.{new_id().int % 250}.{new_id().int % 250}"
    async with http_app(storage_settings, *module_routers(), client_ip=ip) as app:
        yield app


class Account:
    """Пользователь Mini App: запросы к API и данные в БД мимо API."""

    def __init__(self, app: HttpApp, tokens: dict[str, object]) -> None:
        self.app, self.headers, self.user_id = app, bearer(tokens), user_id_of(tokens)

    async def call(self, method: str, path: str, **body: Any) -> httpx.Response:
        headers = self.headers
        if method == "POST":
            headers = headers | {"idempotency-key": new_id().hex}
        return await self.app.client.request(
            method, f"{API}{path}", json=body or None, headers=headers
        )

    async def execute(self, sql: str, **params: object) -> None:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.begin() as conn:
            await conn.execute(text(sql), params)

    async def scalar(self, sql: str, **params: object) -> Any:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).scalar()

    async def media(self, purpose: str) -> str:
        media_id = new_id()
        variants = {"thumb": {"key": f"m/{media_id}/thumb.webp", "w": 320, "h": 240}}
        await self.execute(
            "INSERT INTO media.assets (id, owner_id, kind, purpose, status, bucket, object_key,"
            " mime_type, size_bytes, variants) VALUES (:id, :owner, 'image', :purpose, 'ready',"
            " 'media', :key, 'image/jpeg', 1000, CAST(:variants AS jsonb))",
            id=media_id,
            owner=self.user_id,
            purpose=purpose,
            key=f"{purpose}/2026/10/{media_id}/original",
            variants=json.dumps(variants),
        )
        return str(media_id)

    async def run(self, task: str) -> int:
        return await run_queued(self.app.container, task, user_id=self.user_id)


async def specialist(app: HttpApp, settings: Settings, telegram_id: int) -> Account:
    account = Account(app, await login(app.client, signed_init_data(settings, telegram_id)))
    async with app.container() as request:
        await accept_rules(await request.get(AsyncSession), account.user_id)
    assert await account.run("growth.record_attribution") == 1
    city = await account.scalar("SELECT id FROM geo.cities WHERE slug = 'novi-sad'")
    assert (await account.call("POST", "/me/profile", kind="pro", city_id=city)).status_code == 201
    service = await account.call(
        "POST", "/me/profile/services", title="Вызов мастера", price_type="fixed", price_min=150000
    )
    assert service.status_code == 201
    work = await account.call(
        "POST", "/me/profile/portfolio", media_id=await account.media("portfolio")
    )
    assert work.status_code == 201
    avatar = await account.call("PUT", "/me/profile/avatar", media_id=await account.media("avatar"))
    assert avatar.status_code == 200
    await account.execute(
        "INSERT INTO notifications.channels (id, user_id, kind, address, granted_via, granted_at)"
        " VALUES (:id, :user, 'telegram', :address, 'bot_start', now())",
        id=new_id(),
        user=account.user_id,
        address=str(telegram_id),
    )
    # заявка (5.1): адрес — личный, после удаления аккаунта его нет
    category = await account.scalar(
        "SELECT min(id) FROM catalog.categories WHERE is_active AND jobs_enabled"
        " AND risk_level = 0 AND parent_id IS NOT NULL"
    )
    job = await account.call(
        "POST",
        "/jobs",
        title="Повесить люстру в спальне",
        category_id=category,
        urgency="this_week",
        budget_type="negotiable",
        city_id=city,
        address_private="Народног фронта 12, стан 5",
    )
    assert job.status_code == 201, job.text
    # «не интересно» в ленте (5.3) — строкой: своя заявка в ленте не видна, но строка законна
    await account.execute(
        "INSERT INTO jobs.hidden_jobs (user_id, job_id) VALUES (:user, :job)",
        user=account.user_id,
        job=job.json()["id"],
    )
    # избранное (4.6) — строкой: сохранить через API можно только видимого в каталоге
    await account.execute(
        "INSERT INTO search.favorites (user_id, target_type, target_id)"
        " VALUES (:user, 'profile', :target)",
        user=account.user_id,
        target=new_id(),
    )
    return account


async def count(account: Account, sql: str, **params: object) -> int:
    return int(await account.scalar(sql, **params))


async def test_deleted_account_keeps_nothing_personal(
    app: HttpApp, storage_settings: Settings
) -> None:
    telegram_id = new_telegram_id()
    account = await specialist(app, storage_settings, telegram_id)
    profile_id = await account.scalar(
        "SELECT id FROM specialists.profiles WHERE user_id = :user", user=account.user_id
    )

    requested = await account.call("POST", "/me/deletion")
    assert requested.status_code == 200
    me = (await account.call("GET", "/me")).json()
    assert me["deletion_scheduled_at"] == requested.json()["execute_after"]
    # срок пришёл: grace-период 7 дней — сдвигом срока, а не часов процесса
    await account.execute(
        "UPDATE identity.deletion_requests SET execute_after = now() - interval '1 minute'"
        " WHERE user_id = :user",
        user=account.user_id,
    )
    async with app.container() as request:
        process = await request.get(ProcessDeletions)
        report = await process(ProcessDeletionsCommand())
    assert report.deleted == 1

    for task in (
        "specialists.forget_profile",
        "media.forget_owner",
        "notifications.forget_recipient",
        "growth.forget_attribution",
        "pricing.remove_profile_prices",
        "search.forget_favorites",
        "jobs.forget_client",
    ):
        assert await account.run(task) == 1, task
    assert await account.run("media.discard_media") == 2  # работа и фото профиля

    user = await account.scalar(
        "SELECT status || ':' || display_name FROM identity.users WHERE id = :user",
        user=account.user_id,
    )
    assert user == "deleted:Удалённый пользователь"
    assert (
        await count(
            account,
            "SELECT count(*) FROM identity.auth_identities WHERE user_id = :user",
            user=account.user_id,
        )
        == 0
    )
    profile = await account.scalar(
        "SELECT display_name || ':' || coalesce(headline, '-') FROM specialists.profiles"
        " WHERE id = :id AND deleted_at IS NOT NULL",
        id=profile_id,
    )
    assert profile == "Удалённый пользователь:-"
    left = {
        "работы": "SELECT count(*) FROM specialists.portfolio_items WHERE profile_id = :id"
        " AND deleted_at IS NULL",
        "прайс": "SELECT count(*) FROM pricing.services WHERE profile_id = :id"
        " AND deleted_at IS NULL",
    }
    for what, sql in left.items():
        assert await count(account, sql, id=profile_id) == 0, what
    mine = {
        "файлы": "SELECT count(*) FROM media.assets WHERE owner_id = :user AND deleted_at IS NULL",
        "каналы": "SELECT count(*) FROM notifications.channels WHERE user_id = :user",
        "атрибуция": "SELECT count(*) FROM growth.attributions WHERE user_id = :user",
        "избранное": "SELECT count(*) FROM search.favorites WHERE user_id = :user",
        "заявки": "SELECT count(*) FROM jobs.jobs WHERE client_id = :user"
        " AND (deleted_at IS NULL OR status <> 'closed' OR address_private IS NOT NULL)",
        "скрытые заявки": "SELECT count(*) FROM jobs.hidden_jobs WHERE user_id = :user",
    }
    for what, sql in mine.items():
        assert await count(account, sql, user=account.user_id) == 0, what
    digest = identity_hash(DEV_HASH_KEY, HashKind.TELEGRAM, str(telegram_id))
    assert (
        await count(
            account,
            "SELECT count(*) FROM identity.deleted_identity_hashes WHERE hash = :hash",
            hash=digest,
        )
        == 1
    )
    # сессия отозвана: access-токен больше не принимается
    assert (await account.call("GET", "/me")).status_code == 401


async def test_cancelled_request_keeps_the_account(
    app: HttpApp, storage_settings: Settings
) -> None:
    account = await specialist(app, storage_settings, new_telegram_id())

    assert (await account.call("POST", "/me/deletion")).status_code == 200
    assert (await account.call("DELETE", "/me/deletion")).status_code == 204
    assert (await account.call("DELETE", "/me/deletion")).status_code == 204
    await account.execute(
        "UPDATE identity.deletion_requests SET execute_after = now() - interval '1 minute'"
        " WHERE user_id = :user",
        user=account.user_id,
    )
    async with app.container() as request:
        process = await request.get(ProcessDeletions)
        await process(ProcessDeletionsCommand())

    me = await account.call("GET", "/me")
    assert (me.status_code, me.json()["deletion_scheduled_at"]) == (200, None)
    assert await account.run("specialists.forget_profile") == 0
