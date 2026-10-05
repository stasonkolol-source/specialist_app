"""Диалоги для экранов (DEVELOPMENT_PLAN 6.4) через API: в списке S29 и шапке S30 — имя второй
стороны (у специалиста — с карточки, ссылка на S08), заявка и сделка; вкладки «Я клиент» и «Я
исполнитель»; удалённый аккаунт — без имени. Бейджи таббара: новые отклики на свои заявки и
непрочитанные сообщения. Данные коммитятся.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.entrypoints._wiring import module_routers
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings
from tests.plugins.chat import Chat
from tests.plugins.http import HttpApp, http_app
from tests.plugins.search import NAME, Specialist

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


async def listed(chat: Chat, user: UserId, role: str | None = None) -> dict[str, Any]:
    path = "/conversations" + (f"?role={role}" if role else "")
    reply = await chat.get(user, path)
    assert reply.status_code == 200, reply.text
    return {item["id"]: item for item in reply.json()["items"]}


async def badges(chat: Chat, user: UserId) -> dict[str, int]:
    reply = await chat.get(user, "/me/badges")
    assert reply.status_code == 200, reply.text
    assert reply.headers["cache-control"] == "private, no-store"
    counts: dict[str, int] = reply.json()
    return counts


async def test_cards_name_the_counterpart_job_and_deal_by_role(chat: Chat) -> None:
    specialist = Specialist(chat.app.container)
    await specialist.publish()
    chat.users.append(specialist.user_id)
    direct_client, job_client = await chat.user(), await chat.user()
    direct = await chat.start(direct_client, profile_id=str(specialist.profile_id))
    response_id = await chat.response(specialist.user_id, await chat.job(job_client))
    by_response = await chat.start(job_client, response_id=response_id)
    proposed = await chat.post(
        direct_client, f"/conversations/{direct}/deal", {"title": "Повесить люстру"}
    )
    assert proposed.status_code == 201, proposed.text

    mine = (await listed(chat, direct_client))[direct]
    assert (mine["counterpart_name"], mine["counterpart_profile_id"]) == (
        NAME,
        str(specialist.profile_id),
    )  # имя с карточки специалиста, а не аккаунта
    assert (mine["job_title"], mine["deal"]) == (
        None,
        {"id": proposed.json()["deal_id"], "status": "proposed", "title": "Повесить люстру"},
    )
    theirs = (await listed(chat, job_client))[by_response]
    assert (theirs["job_title"], theirs["counterpart_profile_id"], theirs["deal"]) == (
        "Повесить люстру",
        str(specialist.profile_id),
        None,
    )
    performer_side = await listed(chat, specialist.user_id, "performer")
    assert set(performer_side) == {direct, by_response}
    assert performer_side[direct]["counterpart_name"] == "Ana"  # клиенты — по имени аккаунта
    assert performer_side[direct]["counterpart_profile_id"] is None
    assert await listed(chat, specialist.user_id, "client") == {}
    header = (await chat.messages(job_client, by_response))["conversation"]
    assert header["job_title"] == "Повесить люстру"

    await chat.execute(
        "UPDATE identity.users SET status = 'deleted' WHERE id = :id", id=direct_client
    )
    gone = (await listed(chat, specialist.user_id))[direct]
    assert gone["counterpart_name"] is None


async def test_chat_started_after_the_choice_shows_the_deal(chat: Chat) -> None:
    """UXM-14: отклик уже выбран, диалог начали потом («Поделиться контактом» на S26) — в шапке
    S30 и в S29 сделка этого отклика, а не «Сделки пока нет»; у обеих сторон."""
    client, performer, response_id = await chat.pair()
    accepted = await chat.post(client, f"/responses/{response_id}/accept")
    assert accepted.status_code == 200, accepted.text
    deal_id = accepted.json()["deal_id"]

    conversation = await chat.start(client, response_id=response_id)

    deal = {"id": deal_id, "status": "agreed", "title": "Повесить люстру"}
    header = (await chat.messages(client, conversation))["conversation"]
    assert (header["deal"], header["contacts_open"]) == (deal, True)
    assert (await listed(chat, performer))[conversation]["deal"] == deal


async def test_badges_count_new_responses_and_unread_messages(chat: Chat) -> None:
    client = await chat.user()
    job_id = await chat.job(client)
    first, second = await chat.user(), await chat.user()
    response_id = await chat.response(first, job_id)
    await chat.response(second, job_id)

    assert await badges(chat, client) == {"jobs": 2, "messages": 0}

    conversation_id = await chat.start(client, response_id=response_id)
    await chat.send(first, conversation_id, "Когда удобно?")
    last = await chat.send(first, conversation_id, "Могу сегодня")
    assert (await badges(chat, client))["messages"] == 3  # отклик и два сообщения
    assert (await badges(chat, first))["messages"] == 0  # свои не в счёт

    read = await chat.post(
        client, f"/conversations/{conversation_id}/read", {"message_id": last["id"]}
    )
    assert read.status_code == 204
    assert (await badges(chat, client))["messages"] == 0
    seen = await chat.get(client, f"/jobs/{job_id}/response-cards")  # S23 отмечает отклики
    assert seen.status_code == 200, seen.text
    assert (await badges(chat, client))["jobs"] == 0
