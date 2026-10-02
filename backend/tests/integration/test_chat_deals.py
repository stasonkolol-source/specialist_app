"""Договорённость и контакты в переписке (DEVELOPMENT_PLAN 6.3b) через API: «Договорились» в прямом
диалоге — сделка `proposed`, вторая сторона подтверждает, лента диалога это показывает, контакты
открываются; в диалоге по отклику договорённость — выбор отклика; поделиться контактом — только
после договорённости и только своим (подпись Telegram). Подписчики выполняются из очереди.
Данные коммитятся.
"""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import pytest
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.entrypoints._wiring import make_worker_container, module_routers
from app.modules.messaging.application.use_cases.record_deal_event import (
    RecordDealEvent,
    RecordDealEventCommand,
)
from app.modules.messaging.domain.message import SystemEvent
from app.platform.kernel.ids import UserId, new_id
from app.platform.security.initdata import sign
from app.platform.settings import Settings
from app.platform.telegram.deeplinks import LinkType, StartLink, encode_start_param
from app.platform.text.contact_masking import MASK
from tests.plugins.chat import Chat
from tests.plugins.http import HttpApp, http_app
from tests.plugins.identity import new_telegram_id
from tests.plugins.queue import run_queued
from tests.plugins.search import Specialist

pytestmark = pytest.mark.integration

PHONE = "Мой номер +381 64 123 4567"


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


def signed(settings: Settings, fields: dict[str, str], *, age: timedelta) -> str:
    """Поля, подписанные ботом теста, как это делает Telegram (initData, `requestContact`)."""
    stamped = fields | {"auth_date": str(int((datetime.now(UTC) - age).timestamp()))}
    token = settings.telegram.bot_token.get_secret_value()
    return urlencode(stamped | {"hash": sign(stamped, token)})


def init_data(
    settings: Settings,
    telegram_id: int,
    *,
    username: str | None = "ana_ns",
    age: timedelta = timedelta(hours=3),  # Mini App открыли давно — username всё равно годен
) -> str:
    user: dict[str, object] = {"id": telegram_id, "first_name": "Ana"}
    if username is not None:
        user["username"] = username
    return signed(settings, {"user": json.dumps(user)}, age=age)


def contact(settings: Settings, telegram_id: int, *, age: timedelta = timedelta(seconds=5)) -> str:
    shared = {"user_id": telegram_id, "phone_number": "381641234567", "first_name": "Ana"}
    return signed(settings, {"contact": json.dumps(shared)}, age=age)


class Direct:
    """Прямой диалог клиента со специалистом (у обоих есть Telegram)."""

    def __init__(self, chat: Chat) -> None:
        self.chat = chat
        self.client_tg, self.performer_tg = new_telegram_id(), new_telegram_id()

    async def start(self) -> tuple[UserId, UserId, str]:
        specialist = Specialist(self.chat.app.container)
        await specialist.publish()
        await self.chat.execute(
            "INSERT INTO identity.auth_identities (id, user_id, provider, subject)"
            " VALUES (uuidv7(), :user_id, 'telegram', :subject)",
            user_id=specialist.user_id,
            subject=str(self.performer_tg),
        )
        self.chat.users.append(specialist.user_id)
        client = await self.chat.user(telegram_id=self.client_tg)
        conversation_id = await self.chat.start(client, profile_id=str(specialist.profile_id))
        return client, specialist.user_id, conversation_id


async def propose(chat: Chat, user: UserId, conversation_id: str, **terms: Any) -> Any:
    body = {"title": "Повесить люстру", "price_type": "fixed", "price_amount": 350_000} | terms
    return await chat.post(user, f"/conversations/{conversation_id}/deal", body)


async def events(chat: Chat, user: UserId, conversation_id: str) -> list[dict[str, Any]]:
    items = (await chat.messages(user, conversation_id))["items"]
    return [item["event"] for item in items if item["kind"] == "system"]


async def test_direct_proposal_is_confirmed_by_the_other_side(
    chat: Chat, worker: AsyncContainer
) -> None:
    client, performer, conversation_id = await Direct(chat).start()
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0)

    proposed = await propose(chat, client, conversation_id, scheduled_at=tomorrow.isoformat())

    assert proposed.status_code == 201, proposed.text
    deal_id = proposed.json()["deal_id"]
    deal = (await chat.get(performer, f"/deals/{deal_id}")).json()
    assert (deal["status"], deal["origin"], deal["title"]) == (
        "proposed",
        "chat",
        "Повесить люстру",
    )
    assert deal["price"] == {"type": "fixed", "amount": {"amount": 350_000, "currency": "RSD"}}
    assert await events(chat, performer, conversation_id) == [
        {"type": "deal_proposed", "deal_id": deal_id, "by": "client", "reason": None}
    ]
    page = await chat.messages(performer, conversation_id)
    assert page["conversation"]["deal_id"] == deal_id
    again = await propose(chat, performer, conversation_id)
    assert (again.status_code, again.json()["code"], again.json()["deal_id"]) == (
        409,
        "deal_in_progress",
        deal_id,
    )
    # вторая сторона узнаёт из бота
    assert (
        await run_queued(
            worker, "notifications.notify_deal_proposed", user_id=client, by="client_id"
        )
        == 1
    )
    [(payload,)] = await chat.rows(
        "SELECT payload FROM notifications.notifications WHERE user_id = :user"
        " AND type = 'deal.proposed'",
        user=performer,
    )
    link = encode_start_param(StartLink(type=LinkType.DEAL, id=UUID(deal_id)))
    assert payload == {
        "params": {
            "title": "Повесить люстру",
            "by": "client",
            "deal_id": deal_id,
            "at": tomorrow.isoformat(),
            "price_type": "fixed",
            "price": "350000",
        },
        "link": link,
        "urgent": False,
    }

    masked = await chat.send(performer, conversation_id, PHONE)
    assert masked["body"] == f"Мой номер {MASK}"  # ещё не договорились
    confirmed = await chat.post(performer, f"/deals/{deal_id}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    recorded = await run_queued(
        worker, "messaging.record_deal_agreed", user_id=client, by="client_id"
    )
    assert recorded == 1
    assert [event["type"] for event in await events(chat, client, conversation_id)] == [
        "deal_proposed",
        "deal_agreed",
    ]
    opened = await chat.send(performer, conversation_id, PHONE)
    assert (opened["masked"], opened["body"]) == (False, PHONE)
    # повтор задачи второго «Договорились» в ленту не пишет
    async with worker() as request:
        repeated = await (await request.get(RecordDealEvent))(
            RecordDealEventCommand(
                deal_id=UUID(deal_id),
                response_id=None,
                event=SystemEvent.DEAL_AGREED,
                at=datetime.now(UTC),
            )
        )
    assert repeated is False
    unread = (await chat.mine(client))[conversation_id]["unread"]
    assert unread == 2  # два сообщения исполнителя; системные не в счёт


async def test_declined_proposal_lets_them_agree_again(chat: Chat, worker: AsyncContainer) -> None:
    client, performer, conversation_id = await Direct(chat).start()
    first = (await propose(chat, performer, conversation_id)).json()["deal_id"]

    declined = await chat.post(client, f"/deals/{first}/cancel", {"reason": "no_agreement"})
    assert declined.status_code == 200, declined.text
    assert (
        await run_queued(worker, "messaging.record_deal_cancelled", user_id=client, by="client_id")
        == 1
    )

    assert (await events(chat, client, conversation_id))[-1] == {
        "type": "deal_cancelled",
        "deal_id": first,
        "by": "client",
        "reason": "no_agreement",
    }
    second = await propose(chat, client, conversation_id, title="Повесить две люстры")
    assert second.status_code == 201, second.text
    assert second.json()["deal_id"] != first


async def test_proposal_terms_are_checked(chat: Chat) -> None:
    client, _, conversation_id = await Direct(chat).start()
    path = f"/conversations/{conversation_id}/deal"

    no_type = await chat.post(client, path, {"title": "Люстра", "price_amount": 350_000})
    past = await propose(
        chat,
        client,
        conversation_id,
        scheduled_at=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
    )
    far = await propose(
        chat,
        client,
        conversation_id,
        scheduled_at=(datetime.now(UTC) + timedelta(days=120)).isoformat(),
    )
    negotiable = await propose(chat, client, conversation_id, price_type="negotiable")
    empty = await chat.post(client, path, {"title": ""})

    assert [
        (r.status_code, r.json().get("field"), r.json().get("reason"))
        for r in (no_type, past, far, negotiable)
    ] == [
        (422, "price_type", "required"),
        (422, "scheduled_at", "past"),
        (422, "scheduled_at", "too_far"),
        (422, "agreed_price", "negotiable_has_amount"),
    ]
    assert empty.status_code == 422
    stranger = await propose(chat, await chat.user(), conversation_id)
    assert stranger.status_code == 404


async def test_response_conversation_agrees_by_choosing_the_response(
    chat: Chat, worker: AsyncContainer
) -> None:
    client, performer, response_id = await chat.pair()
    conversation_id = await chat.start(performer, response_id=response_id)

    refused = await propose(chat, performer, conversation_id)
    assert (refused.status_code, refused.json()["code"], refused.json()["reason"]) == (
        409,
        "cannot_propose",
        "choose_response",
    )
    accepted = await chat.post(client, f"/responses/{response_id}/accept")
    assert accepted.status_code == 200, accepted.text
    assert (
        await run_queued(worker, "messaging.record_deal_agreed", user_id=client, by="client_id")
        == 1
    )

    page = await chat.messages(performer, conversation_id)
    assert page["conversation"]["deal_id"] == accepted.json()["deal_id"]
    assert [item["event"]["type"] for item in page["items"] if item["kind"] == "system"] == [
        "deal_agreed"
    ]


async def test_contact_is_shared_after_the_deal_and_only_ones_own(
    chat: Chat, worker: AsyncContainer
) -> None:
    direct = Direct(chat)
    client, performer, conversation_id = await direct.start()
    path = f"/conversations/{conversation_id}/share-contact"
    settings = chat.settings
    telegram = {"contact_type": "telegram", "init_data": init_data(settings, direct.client_tg)}

    locked = await chat.post(client, path, telegram)
    assert (locked.status_code, locked.json()["code"]) == (409, "contacts_locked")

    deal_id = (await propose(chat, client, conversation_id)).json()["deal_id"]
    assert (await chat.post(performer, f"/deals/{deal_id}/confirm")).status_code == 200
    shared = await chat.post(client, path, telegram)
    again = await chat.post(client, path, telegram)
    phone = await chat.post(
        performer,
        path,
        {"contact_type": "phone", "contact": contact(settings, direct.performer_tg)},
    )

    assert shared.status_code == 201, shared.text
    assert (again.status_code, again.json()["id"]) == (200, shared.json()["id"])
    assert shared.json()["contact"] == {"type": "telegram", "value": "@ana_ns"}
    assert phone.status_code == 201, phone.text
    seen = [
        (item["kind"], item["mine"], item["contact"])
        for item in (await chat.messages(client, conversation_id))["items"]
        if item["kind"] == "contact_share"
    ]
    assert seen == [
        ("contact_share", True, {"type": "telegram", "value": "@ana_ns"}),
        ("contact_share", False, {"type": "phone", "value": "+381641234567"}),
    ]
    queued = await chat.scalar(
        "SELECT count(*) FROM procrastinate_jobs WHERE task_name ="
        " 'analytics.capture_contact_shared' AND args->'payload'->>'conversation_id' = :id",
        id=conversation_id,
    )
    assert queued == 2
    noticed = await chat.scalar(
        "SELECT count(*) FROM procrastinate_jobs WHERE task_name ="
        " 'notifications.schedule_messages_notice' AND args->'payload'->>'message_id' = :id",
        id=shared.json()["id"],
    )
    assert noticed == 1  # контакт — сообщение: второй стороне придёт уведомление

    async def refused(user: UserId, body: dict[str, str]) -> tuple[int, str]:
        reply = await chat.post(user, path, body)
        return reply.status_code, reply.json().get("reason")

    stranger_tg = new_telegram_id()
    assert await refused(
        performer, {"contact_type": "phone", "contact": contact(settings, stranger_tg)}
    ) == (422, "not_yours")
    assert await refused(
        performer,
        {
            "contact_type": "phone",
            "contact": contact(settings, direct.performer_tg, age=timedelta(hours=2)),
        },
    ) == (422, "expired")
    tampered = contact(settings, direct.performer_tg).replace("381641234567", "381640000000")
    assert await refused(performer, {"contact_type": "phone", "contact": tampered}) == (
        422,
        "signature",
    )
    assert await refused(
        performer,
        {
            "contact_type": "telegram",
            "init_data": init_data(settings, direct.performer_tg, username=None),
        },
    ) == (422, "no_username")
    assert await refused(performer, {"contact_type": "telegram"}) == (422, "missing")
