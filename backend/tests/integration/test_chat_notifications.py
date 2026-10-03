"""Уведомление о сообщениях (DEVELOPMENT_PLAN 6.3b; ARCHITECTURE §11.3): серия сообщений за минуту —
одно `message.received` в конце окна («Ana пишет», начало последнего, сколько новых, «Ответить» —
ссылка `c_`); получателю, который смотрит диалог (поллинг S30) или уже прочитал, — ничего.
Подписчики выполняются из очереди. Данные коммитятся.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.entrypoints._wiring import make_worker_container, module_routers
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings
from app.platform.telegram.deeplinks import LinkType, StartLink, encode_start_param
from tests.plugins.chat import Chat
from tests.plugins.http import HttpApp, http_app
from tests.plugins.queue import run_queued

pytestmark = pytest.mark.integration


@pytest.fixture
async def web(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[HttpApp]:
    ip = f"10.{new_id().int % 250}.{new_id().int % 250}.{new_id().int % 250}"
    async with http_app(storage_settings, *module_routers(), client_ip=ip) as app:
        yield app


@pytest.fixture
async def worker(storage_settings: Settings) -> AsyncIterator[AsyncContainer]:
    container = make_worker_container(storage_settings)
    try:
        yield container
    finally:
        await container.close()


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


async def notices(chat: Chat, user: UserId) -> list[dict[str, Any]]:
    rows = await chat.rows(
        "SELECT payload FROM notifications.notifications WHERE user_id = :user"
        " AND type = 'message.received' ORDER BY id",
        user=user,
    )
    return [payload for (payload,) in rows]


async def window_ends(chat: Chat, recipient: UserId) -> list[datetime]:
    rows = await chat.rows(
        "SELECT scheduled_at FROM procrastinate_jobs WHERE task_name ="
        " 'notifications.notify_messages' AND status = 'todo'"
        " AND args->'payload'->>'recipient_id' = :id",
        id=str(recipient),
    )
    return [at for (at,) in rows]


async def schedule(worker: AsyncContainer, sender: UserId) -> int:
    return await run_queued(
        worker, "notifications.schedule_messages_notice", user_id=sender, by="sender_id"
    )


async def deliver(worker: AsyncContainer, recipient: UserId) -> int:
    return await run_queued(
        worker, "notifications.notify_messages", user_id=recipient, by="recipient_id"
    )


async def test_burst_of_messages_is_one_notice(chat: Chat, worker: AsyncContainer) -> None:
    client, performer, response_id = await chat.pair()
    conversation_id = await chat.start(client, response_id=response_id)
    started = datetime.now(UTC)
    for body in ("Добрый день!", "Когда удобно?", "Могу сегодня в 19:00"):
        await chat.send(performer, conversation_id, body)

    assert await schedule(worker, performer) == 3
    [ends] = await window_ends(chat, client)  # одно окно на серию
    assert ends >= started + timedelta(seconds=55)
    assert await deliver(worker, client) == 1

    link = encode_start_param(StartLink(type=LinkType.CHAT, id=UUID(conversation_id)))
    assert await notices(chat, client) == [
        {
            "params": {"name": "Ana", "count": "4", "preview": "Могу сегодня в 19:00"},
            "link": link,
            "urgent": False,
        }
    ]  # отклик и три сообщения
    assert await notices(chat, performer) == []  # о своих не пишем


async def test_open_dialog_or_read_messages_need_no_notice(
    chat: Chat, worker: AsyncContainer
) -> None:
    client, performer, response_id = await chat.pair()
    conversation_id = await chat.start(client, response_id=response_id)

    # клиент смотрит диалог: S30 опрашивает новые
    await chat.messages(client, conversation_id)
    await chat.send(performer, conversation_id, "Вы тут?")
    assert await schedule(worker, performer) == 1
    assert await deliver(worker, client) == 1
    assert await notices(chat, client) == []

    # исполнитель диалог не открывал, но прочитал ответ до конца окна (из списка S29)
    reply = await chat.send(client, conversation_id, "Да, слушаю")
    read = await chat.post(
        performer, f"/conversations/{conversation_id}/read", {"message_id": reply["id"]}
    )
    assert read.status_code == 204
    assert await schedule(worker, client) == 1
    assert await deliver(worker, performer) == 1
    assert await notices(chat, performer) == []

    # не прочитал и не смотрит — уведомление уходит
    await chat.send(client, conversation_id, "Жду ответа")
    assert await schedule(worker, client) == 1
    assert await deliver(worker, performer) == 1
    [notice] = await notices(chat, performer)
    assert notice["params"] == {"name": "Ana", "count": "1", "preview": "Жду ответа"}
