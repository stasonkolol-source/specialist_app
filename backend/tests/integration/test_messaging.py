"""Переписка (DEVELOPMENT_PLAN 6.3a) через API: диалог по отклику начинается самим откликом и не
двоится, прямой — из карточки специалиста; до договорённости контакты в тексте скрыты, после
выбора исполнителя — нет; повтор `client_msg_id` не дублирует сообщение и его события; страницы
назад, поллинг новых и 304 по ETag; непрочитанные и «прочитано»; чужой диалог — 404, закрытый —
только читать; санкция «переписка» и часовые лимиты; модерация скрывает текст от второй стороны;
удаление аккаунта и срок хранения стирают текст. Данные коммитятся.
"""

import re
from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._wiring import make_worker_container, module_routers
from app.modules.messaging.api import MessagingApi
from app.modules.messaging.application.use_cases.forget_messages import (
    ForgetMessages,
    ForgetMessagesCommand,
)
from app.modules.messaging.infrastructure.queries import unread_total_query
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import new_id
from app.platform.settings import Settings
from app.platform.text.contact_masking import MASK
from tests.plugins.chat import API, Chat
from tests.plugins.http import HttpApp, http_app
from tests.plugins.identity import insert_restriction
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


@pytest.mark.authz
async def test_response_conversation_starts_with_the_offer_once(chat: Chat) -> None:
    client, performer, response_id = await chat.pair()
    stranger = await chat.user()

    started = await chat.post(client, "/conversations", {"response_id": response_id})
    again = await chat.post(performer, "/conversations", {"response_id": response_id})

    assert (started.status_code, started.json()["created"]) == (201, True)
    assert (again.status_code, again.json()) == (
        200,
        {"id": started.json()["id"], "created": False},
    )
    conversation_id = started.json()["id"]
    page = await chat.messages(client, conversation_id)
    [offer] = page["items"]
    assert (offer["kind"], offer["mine"], offer["sender_id"]) == ("offer", False, str(performer))
    assert offer["body"].startswith("Здравствуйте! Могу сегодня в 19:00.")
    assert offer["offer"] == {
        "price_type": "fixed",
        "price_amount": 350_000,
        "availability_note": "Сегодня, 19:00",
    }
    conversation = page["conversation"]
    assert (conversation["kind"], conversation["my_role"], conversation["counterpart_id"]) == (
        "job_response",
        "client",
        str(performer),
    )
    assert conversation["response_id"] == response_id
    # чужому — как будто диалога нет
    assert (
        await chat.get(stranger, f"/conversations/{conversation_id}/messages")
    ).status_code == 404
    foreign = await chat.post(stranger, "/conversations", {"response_id": response_id})
    assert (foreign.status_code, foreign.json()["code"]) == (404, "conversation_not_found")
    assert await chat.mine(stranger) == {}
    started_events = await chat.scalar(
        "SELECT count(*) FROM procrastinate_jobs WHERE task_name ="
        " 'analytics.capture_conversation_started' AND args->'payload'->>'conversation_id' = :id",
        id=conversation_id,
    )
    assert started_events == 1


async def test_contacts_are_masked_until_the_deal(chat: Chat) -> None:
    client, performer = await chat.user(), await chat.user()
    response_id = await chat.response(performer, await chat.job(client), f"Звоните: {PHONE[10:]}")
    conversation_id = await chat.start(client, response_id=response_id)

    [offer] = (await chat.messages(client, conversation_id))["items"]
    before = await chat.send(performer, conversation_id, PHONE)
    prepayment = await chat.send(client, conversation_id, "Нужна предоплата 50% на карту?")

    assert (offer["masked"], MASK in offer["body"]) == (True, True)
    assert (before["masked"], before["body"]) == (True, f"Мой номер {MASK}")
    assert (prepayment["prepayment"], prepayment["masked"]) == (True, False)

    accepted = await chat.post(client, f"/responses/{response_id}/accept")
    assert accepted.status_code == 200, accepted.text
    after = await chat.send(performer, conversation_id, PHONE)
    assert (after["masked"], after["body"]) == (False, PHONE)
    # что ушло до договорённости, так и остаётся скрытым
    items = (await chat.messages(client, conversation_id))["items"]
    assert [item["body"] for item in items[1:]] == [
        f"Мой номер {MASK}",
        "Нужна предоплата 50% на карту?",
        PHONE,
    ]


async def test_contact_split_across_messages_is_masked_in_every_part(chat: Chat) -> None:
    """QA ADV-06: номер и ник по частям в нескольких сообщениях скрыты — в новом сообщении и
    задним числом в прежних частях (их перечитывают уже скрытыми, с отметкой masked); обычные
    числа (цены, даты, адрес) не трогаются."""
    client, performer = await chat.user(), await chat.user()
    response_id = await chat.response(performer, await chat.job(client), "Добрый день!")
    conversation_id = await chat.start(client, response_id=response_id)
    texts = [
        "064",
        "123 45 67",
        "мой номер начинается 064",
        "потом 123",
        "и в конце 45 67",
        "мой ник @qa",
        "_contact_test",
        "Цена 3000",
        "или 2500 со скидкой, буду 07.10 в 18:00",
        "Улица Футошка 12, квартира 5",
    ]

    sent = [await chat.send(performer, conversation_id, body) for body in texts]

    # новое сообщение скрыто сразу, а первая часть при отправке ещё не была контактом
    assert [message["masked"] for message in sent[:2]] == [False, True]
    items = (await chat.messages(client, conversation_id))["items"][1:]
    assert [(item["body"], item["masked"]) for item in items] == [
        (MASK, True),
        (MASK, True),
        (f"мой номер начинается {MASK}", True),
        (f"потом {MASK}", True),
        (f"и в конце {MASK}", True),
        (f"мой ник {MASK}", True),
        (MASK, True),
        ("Цена 3000", False),
        ("или 2500 со скидкой, буду 07.10 в 18:00", False),
        ("Улица Футошка 12, квартира 5", False),
    ]
    # отметка «скрыты контакты» — как у контакта в одном сообщении: в событии нового сообщения
    masked_events = await chat.scalar(
        "SELECT count(*) FROM procrastinate_jobs WHERE task_name ="
        " 'analytics.capture_message_sent' AND args->'payload'->>'sender_id' = :sender"
        " AND (args->'payload'->>'masked')::boolean",
        sender=str(performer),
    )
    assert masked_events == 3


async def test_split_contact_after_the_deal_stays_open(chat: Chat) -> None:
    """Контакты в диалоге уже открыты (договорились) — части номера не скрываются."""
    client, performer, response_id = await chat.pair()
    conversation_id = await chat.start(client, response_id=response_id)
    accepted = await chat.post(client, f"/responses/{response_id}/accept")
    assert accepted.status_code == 200, accepted.text

    sent = [await chat.send(performer, conversation_id, body) for body in ("064", "123 45 67")]

    assert [message["masked"] for message in sent] == [False, False]
    items = (await chat.messages(client, conversation_id))["items"]
    assert [item["body"] for item in items[-2:]] == ["064", "123 45 67"]


async def test_repeated_send_is_one_message(chat: Chat) -> None:
    client, performer, response_id = await chat.pair()
    conversation_id = await chat.start(performer, response_id=response_id)
    other_id = await chat.start(
        performer, response_id=await chat.response(performer, await chat.job(client))
    )

    first = await chat.send(client, conversation_id, "Добрый день!", client_msg_id="m-1")
    second = await chat.send(client, conversation_id, "Добрый день!", client_msg_id="m-1")
    reused = await chat.post(
        client, f"/conversations/{other_id}/messages", {"body": "Да", "client_msg_id": "m-1"}
    )

    assert second["id"] == first["id"]
    assert first["client_msg_id"] == "m-1"
    assert (reused.status_code, reused.json()["code"]) == (422, "invalid_message")
    items = (await chat.messages(client, conversation_id))["items"]
    assert [item["kind"] for item in items] == ["offer", "text"]
    assert items[1]["client_msg_id"] == "m-1"
    assert (await chat.messages(performer, conversation_id))["items"][1]["client_msg_id"] is None
    queued = await chat.scalar(
        "SELECT count(*) FROM procrastinate_jobs WHERE task_name = 'moderation.auto_check'"
        " AND args->'payload'->>'entity_id' = :id",
        id=first["id"],
    )
    assert queued == 1  # повтор не ставит событий


@pytest.mark.authz
async def test_stranger_closed_and_restricted_cannot_write(chat: Chat) -> None:
    client, performer, response_id = await chat.pair()
    stranger = await chat.user()
    conversation_id = await chat.start(client, response_id=response_id)

    foreign = await chat.post(
        stranger, f"/conversations/{conversation_id}/messages", {"body": "Эй"}
    )
    assert (foreign.status_code, foreign.json()["code"]) == (404, "conversation_not_found")
    async with chat.app.container() as request:
        await insert_restriction(await request.get(AsyncSession), performer, "messaging_blocked")
    blocked = await chat.post(
        performer, f"/conversations/{conversation_id}/messages", {"body": "Да"}
    )
    assert (blocked.status_code, blocked.json()["code"]) == (403, "restricted")
    restarted = await chat.post(performer, "/conversations", {"response_id": response_id})
    assert (restarted.status_code, restarted.json()["code"]) == (403, "restricted")

    await chat.execute(
        "UPDATE messaging.conversations SET status = 'closed' WHERE id = :id",
        id=UUID(conversation_id),
    )
    closed = await chat.post(client, f"/conversations/{conversation_id}/messages", {"body": "Ау"})
    assert (closed.status_code, closed.json()["code"]) == (409, "conversation_closed")
    assert closed.json()["conversation_status"] == "closed"
    assert len((await chat.messages(client, conversation_id))["items"]) == 1  # читать можно
    empty = await chat.post(client, f"/conversations/{conversation_id}/messages", {"body": " "})
    assert empty.status_code == 409  # закрыт раньше, чем проверен текст


async def test_pages_polling_and_etag(chat: Chat) -> None:
    client, performer, response_id = await chat.pair()
    conversation_id = await chat.start(client, response_id=response_id)
    sent = [await chat.send(client, conversation_id, f"Сообщение {n}") for n in range(4)]

    last = await chat.messages(client, conversation_id, limit=2)
    assert [item["id"] for item in last["items"]] == [sent[2]["id"], sent[3]["id"]]
    earlier = await chat.messages(
        client, conversation_id, limit=2, cursor=last["older_cursor"], direction="older"
    )
    assert [item["id"] for item in earlier["items"]] == [sent[0]["id"], sent[1]["id"]]
    first = await chat.messages(
        client, conversation_id, limit=2, cursor=earlier["older_cursor"], direction="older"
    )
    assert ([item["kind"] for item in first["items"]], first["older_cursor"]) == (["offer"], None)

    path = f"/conversations/{conversation_id}/messages"
    initial = await chat.get(client, path)
    assert initial.headers["cache-control"] == "private, no-cache"
    unchanged = await chat.get(client, path, **{"if-none-match": initial.headers["etag"]})
    assert unchanged.status_code == 304
    reply = await chat.send(performer, conversation_id, "Ответ")
    polled = await chat.messages(
        client, conversation_id, cursor=initial.json()["newer_cursor"], direction="newer"
    )
    assert [item["id"] for item in polled["items"]] == [reply["id"]]
    quiet = await chat.messages(
        client, conversation_id, cursor=polled["newer_cursor"], direction="newer"
    )
    assert (quiet["items"], quiet["newer_cursor"]) == ([], polled["newer_cursor"])
    changed = await chat.get(client, path, **{"if-none-match": initial.headers["etag"]})
    assert changed.status_code == 200


async def test_unread_count_is_an_index_range(chat: Chat) -> None:
    """Перф-аудит: непрочитанные считаются диапазоном индекса (conversation_id, id) от границы
    прочитанного, а не фильтром по всем сообщениям диалогов (`IS NULL OR id > …`)."""
    client, performer, response_id = await chat.pair()
    await chat.start(performer, response_id=response_id)
    sql = unread_total_query(client).compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    engine = await chat.app.container.get(AsyncEngine)
    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL enable_seqscan = off"))  # маленькая база теста
        plan = "\n".join((await conn.execute(text(f"EXPLAIN {sql}"))).scalars())
    assert re.search(r"Index Cond: .*\(id > COALESCE\(", plan), plan


@pytest.mark.authz
async def test_unread_until_read(chat: Chat) -> None:
    client, performer, response_id = await chat.pair()
    conversation_id = await chat.start(performer, response_id=response_id)
    await chat.send(performer, conversation_id, "Когда удобно?")
    last = await chat.send(performer, conversation_id, "Могу завтра")

    mine = await chat.mine(client)
    assert mine[conversation_id]["unread"] == 3  # отклик и два сообщения
    assert mine[conversation_id]["last_message"]["id"] == last["id"]
    assert (await chat.mine(performer))[conversation_id]["unread"] == 0  # свои не в счёт

    read = await chat.post(
        client, f"/conversations/{conversation_id}/read", {"message_id": last["id"]}
    )
    assert read.status_code == 204
    assert (await chat.mine(client))[conversation_id]["unread"] == 0
    reply = await chat.send(client, conversation_id, "Завтра в 10")
    mine = await chat.mine(performer)
    assert (mine[conversation_id]["unread"], mine[conversation_id]["last_message"]["id"]) == (
        1,
        reply["id"],
    )
    foreign = await chat.post(
        await chat.user(), f"/conversations/{conversation_id}/read", {"message_id": last["id"]}
    )
    assert foreign.status_code == 404
    unknown = await chat.post(
        client, f"/conversations/{conversation_id}/read", {"message_id": str(new_id())}
    )
    assert (unknown.status_code, unknown.json()["reason"]) == (422, "not_in_conversation")


async def test_conversations_are_listed_by_activity(chat: Chat) -> None:
    client = await chat.user()
    job_id = await chat.job(client)
    conversations = []
    for _ in range(3):
        performer = await chat.user()
        response_id = await chat.response(performer, job_id)
        conversations.append(await chat.start(client, response_id=response_id))
    await chat.send(client, conversations[0], "Вы ещё свободны?")

    first = await chat.get(client, "/conversations?limit=2")
    page = first.json()
    assert [item["id"] for item in page["items"]] == [conversations[0], conversations[2]]
    rest = await chat.get(client, f"/conversations?limit=2&cursor={page['next_cursor']}")
    assert ([item["id"] for item in rest.json()["items"]], rest.json()["next_cursor"]) == (
        [conversations[1]],
        None,
    )


async def test_direct_conversation_from_the_card(chat: Chat) -> None:
    specialist = Specialist(chat.app.container)
    await specialist.publish()
    client = await chat.user()

    started = await chat.post(client, "/conversations", {"profile_id": str(specialist.profile_id)})
    again = await chat.post(client, "/conversations", {"profile_id": str(specialist.profile_id)})

    assert (started.status_code, again.status_code) == (201, 200)
    assert again.json()["id"] == started.json()["id"]
    conversation_id = started.json()["id"]
    page = await chat.messages(specialist.user_id, conversation_id)
    assert page["items"] == []
    assert (page["conversation"]["kind"], page["conversation"]["my_role"]) == (
        "direct",
        "performer",
    )
    hello = await chat.send(client, conversation_id, "Здравствуйте! Нужна люстра.")
    assert [
        item["id"] for item in (await chat.messages(specialist.user_id, conversation_id))["items"]
    ] == [hello["id"]]
    myself = await chat.post(
        specialist.user_id, "/conversations", {"profile_id": str(specialist.profile_id)}
    )
    assert (myself.status_code, myself.json()["code"], myself.json()["reason"]) == (
        409,
        "cannot_start_conversation",
        "self",
    )
    unknown = await chat.post(client, "/conversations", {"profile_id": str(new_id())})
    assert (unknown.status_code, unknown.json()["reason"]) == (409, "profile_unavailable")
    both = await chat.post(
        client,
        "/conversations",
        {"profile_id": str(specialist.profile_id), "response_id": str(new_id())},
    )
    assert both.status_code == 422


async def test_hourly_limits(chat: Chat) -> None:
    client = await chat.user()
    jobs = [await chat.job(client), await chat.job(client)]  # на заявке — до пяти откликов
    responses = [await chat.response(await chat.user(), jobs[n % 2]) for n in range(6)]

    started = [await chat.post(client, "/conversations", {"response_id": r}) for r in responses]

    assert [reply.status_code for reply in started[:5]] == [201] * 5
    assert (started[5].status_code, started[5].json()["code"]) == (429, "conversations_limit")
    assert "retry-after" in started[5].headers
    # уже начатый диалог лимит не тратит
    assert (
        await chat.post(client, "/conversations", {"response_id": responses[0]})
    ).status_code == 200
    conversation_id = started[0].json()["id"]
    path = f"/conversations/{conversation_id}/messages"
    statuses = [(await chat.post(client, path, {"body": f"№{n}"})).status_code for n in range(21)]
    assert statuses == [201] * 20 + [429]
    trusted = await chat.app.client.post(
        f"{API}{path}", json={"body": "Ещё"}, headers=chat.headers(client, trust_level=2)
    )
    assert trusted.status_code == 201  # проверенным — 100 в час


async def test_moderation_hides_the_text_from_the_other_side(
    chat: Chat, worker: AsyncContainer
) -> None:
    client, performer, response_id = await chat.pair()
    conversation_id = await chat.start(client, response_id=response_id)
    message = await chat.send(performer, conversation_id, "Пишите сюда")

    # автопроверка (отклик и сообщение): чистый текст — сообщение по-прежнему видно
    assert await run_queued(worker, "moderation.auto_check", user_id=performer, by="author_id") == 2
    assert (await chat.messages(client, conversation_id))["items"][1]["body"] == "Пишите сюда"

    async with worker() as request:
        messaging, uow = await request.get(MessagingApi), await request.get(UnitOfWork)
        async with uow:
            await messaging.hide_message(UUID(message["id"]))
        assert await messaging.message_for_review(UUID(message["id"])) is None
        # карточке кейса в чате модераторов (2.5b) скрытый текст нужен — его и проверяют
        card = await messaging.message_for_card(UUID(message["id"]))
        assert card is not None
        assert (card.sender_id, card.text) == (performer, "Пишите сюда")

    seen = (await chat.messages(client, conversation_id))["items"][1]
    assert (seen["hidden"], seen["body"]) == (True, None)
    own = (await chat.messages(performer, conversation_id))["items"][1]
    assert (own["hidden"], own["body"]) == (True, "Пишите сюда")
    assert (await chat.mine(client))[conversation_id]["unread"] == 1  # скрытое не в счёт

    async with worker() as request:
        messaging, uow = await request.get(MessagingApi), await request.get(UnitOfWork)
        async with uow:
            await messaging.approve_message(UUID(message["id"]))
    seen = (await chat.messages(client, conversation_id))["items"][1]
    assert (seen["hidden"], seen["body"]) == (False, "Пишите сюда")


async def test_review_text_has_no_contacts(chat: Chat, worker: AsyncContainer) -> None:
    """Контакты — правило переписки: после договорённости они разрешены, модерация их не видит."""
    client, performer, response_id = await chat.pair()
    conversation_id = await chat.start(client, response_id=response_id)
    assert (await chat.post(client, f"/responses/{response_id}/accept")).status_code == 200
    message = await chat.send(performer, conversation_id, PHONE)

    async with worker() as request:
        messaging = await request.get(MessagingApi)
        review = await messaging.message_for_review(UUID(message["id"]))
        card = await messaging.message_for_card(UUID(message["id"]))

    assert review is not None
    assert (review.sender_id, review.text) == (performer, f"Мой номер {MASK}")
    assert card == review  # и в карточку кейса для модераторов — без номера


async def test_deleted_account_erases_the_text(chat: Chat, worker: AsyncContainer) -> None:
    """Срок хранения переписки — правило `messaging.conversations` (test_retention.py)."""
    client, performer, response_id = await chat.pair()
    conversation_id = await chat.start(client, response_id=response_id)
    gone = await chat.send(performer, conversation_id, "Буду в 19:00")
    kept = await chat.send(client, conversation_id, "Жду")

    async with worker() as request:
        forgotten = await (await request.get(ForgetMessages))(
            ForgetMessagesCommand(user_id=performer)
        )

    assert forgotten == 2  # отклик и сообщение
    rows = {
        message["id"]: await chat.scalar(
            "SELECT body FROM messaging.messages WHERE id = :id", id=UUID(message["id"])
        )
        for message in (gone, kept)
    }
    assert rows == {gone["id"]: None, kept["id"]: "Жду"}
