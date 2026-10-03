"""Контакты после договорённости и приватность (DEVELOPMENT_PLAN 6.5) через API: «Показывать после
договорённости» (`PATCH /me/privacy`, по умолчанию Telegram виден); до договорённости Telegram
второй стороны не виден ни в чате, ни в сделке, после — виден, если она его показывает;
выключенная настройка его скрывает. У предложения «Договорились» — когда предложено и когда
истечёт (S53). Данные коммитятся.
"""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.entrypoints._wiring import module_routers
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings
from tests.plugins.chat import Chat
from tests.plugins.http import HttpApp, http_app
from tests.plugins.identity import new_telegram_id
from tests.plugins.search import Specialist

pytestmark = pytest.mark.integration


@pytest.fixture
async def web(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[HttpApp]:
    ip = f"10.{new_id().int % 250}.{new_id().int % 250}.{new_id().int % 250}"
    async with http_app(storage_settings, *module_routers(), client_ip=ip) as app:
        yield app


@pytest.fixture
async def chat(web: HttpApp, storage_settings: Settings) -> AsyncIterator[Chat]:
    created = Chat(web, storage_settings)
    yield created
    engine = await web.container.get(AsyncEngine)
    async with engine.begin() as conn:
        for user_id in created.users:
            await conn.execute(
                text(
                    "DELETE FROM procrastinate_jobs WHERE status = 'todo' AND args::text LIKE :id"
                ),
                {"id": f"%{user_id}%"},
            )


async def with_username(chat: Chat, user_id: UserId, username: str) -> None:
    """Вход через Telegram: username в снимке профиля способа входа."""
    await chat.execute(
        "INSERT INTO identity.auth_identities (id, user_id, provider, subject, profile)"
        " VALUES (uuidv7(), :user_id, 'telegram', :subject, CAST(:profile AS jsonb))"
        " ON CONFLICT (provider, subject) DO NOTHING",
        user_id=user_id,
        subject=str(new_telegram_id()),
        profile=f'{{"first_name": "Ana", "username": "{username}"}}',
    )


async def card(chat: Chat, user: UserId, deal_id: str) -> Any:
    reply = await chat.get(user, f"/deals/{deal_id}/card")
    assert reply.status_code == 200, reply.text
    return reply.json()


async def header(chat: Chat, user: UserId, conversation_id: str) -> Any:
    return (await chat.messages(user, conversation_id))["conversation"]


async def test_telegram_shows_after_the_deal_unless_hidden(chat: Chat) -> None:
    specialist = Specialist(chat.app.container)
    await specialist.publish()
    chat.users.append(specialist.user_id)
    client = await chat.user()
    await with_username(chat, UserId(specialist.user_id), "majstor_pera")
    await with_username(chat, client, "ana_ns")
    conversation_id = await chat.start(client, profile_id=str(specialist.profile_id))

    me = (await chat.get(client, "/me")).json()
    assert me["privacy"] == {"show_telegram": True}  # по умолчанию показываем

    proposed = await chat.post(
        client, f"/conversations/{conversation_id}/deal", {"title": "Повесить люстру"}
    )
    deal_id = proposed.json()["deal_id"]
    waiting = await card(chat, specialist.user_id, deal_id)
    assert waiting["counterpart"]["telegram"] is None  # ещё не договорились
    assert waiting["awaits_my_confirmation"] is True
    proposed_at = datetime.fromisoformat(waiting["proposed_at"])
    expires_at = datetime.fromisoformat(waiting["proposal_expires_at"])
    assert expires_at - proposed_at == timedelta(hours=72)
    assert (await header(chat, specialist.user_id, conversation_id))["counterpart_telegram"] is None

    confirmed = await chat.post(specialist.user_id, f"/deals/{deal_id}/confirm")
    assert confirmed.status_code == 200, confirmed.text

    agreed = await card(chat, specialist.user_id, deal_id)
    assert agreed["counterpart"]["telegram"] == "@ana_ns"
    assert agreed["proposal_expires_at"] is None
    assert (await card(chat, client, deal_id))["counterpart"]["telegram"] == "@majstor_pera"
    assert (await header(chat, client, conversation_id))["counterpart_telegram"] == "@majstor_pera"

    hidden = await chat.app.client.patch(
        "/api/v1/me/privacy", json={"show_telegram": False}, headers=chat.headers(client)
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["privacy"] == {"show_telegram": False}
    assert (await card(chat, specialist.user_id, deal_id))["counterpart"]["telegram"] is None
    listed = await chat.get(specialist.user_id, "/conversations")
    [item] = [i for i in listed.json()["items"] if i["id"] == conversation_id]
    assert item["counterpart_telegram"] is None
