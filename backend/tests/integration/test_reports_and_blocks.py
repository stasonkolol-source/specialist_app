"""Жалобы и блокировки (DEVELOPMENT_PLAN 4.7) через API: жалоба — кейс P1 или P0, повтор — та же
жалоба, двадцать первая за сутки — 429 (счётчик в Valkey); заблокированный не виден в выдаче
S05, счётчике и избранном, его заявок нет в ленте, на них не откликнуться, его не пригласить,
переписка с ним — только чтение; разблокировали — всё вернулось. Данные коммитятся.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.entrypoints._wiring import module_routers
from app.modules.jobs.domain.job import MAX_BUDGET
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings
from tests.plugins.chat import API, Chat
from tests.plugins.http import HttpApp, http_app
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


async def block(chat: Chat, actor: UserId, user: UserId) -> None:
    reply = await chat.app.client.put(f"{API}/me/blocks/{user}", headers=chat.headers(actor))
    assert reply.status_code == 204, reply.text


async def unblock(chat: Chat, actor: UserId, user: UserId) -> None:
    reply = await chat.app.client.delete(f"{API}/me/blocks/{user}", headers=chat.headers(actor))
    assert reply.status_code == 204, reply.text


async def report(chat: Chat, reporter: UserId, **body: Any) -> httpx.Response:
    return await chat.post(reporter, "/reports", {"reason": "fraud", **body})


async def listed_alone(chat: Chat) -> tuple[Specialist, int]:
    """Опубликованный специалист в read-model, один в своём «городе» выдачи: другие тесты пишут в
    ту же базу, а выдача — по городу."""
    specialist = Specialist(chat.app.container)
    await specialist.publish()
    await specialist.handle("search.on_profile_published")
    city = 900_000 + new_id().int % 99_999
    await chat.execute(
        "UPDATE search.specialist_index SET city_id = :city WHERE profile_id = :id",
        city=city,
        id=specialist.profile_id,
    )
    chat.users.append(specialist.user_id)
    return specialist, city


async def found(chat: Chat, viewer: UserId | None, city: int) -> tuple[list[str], int]:
    headers = chat.headers(viewer) if viewer is not None else {}
    page = await chat.app.client.get(
        f"{API}/specialists", params={"city_id": city}, headers=headers
    )
    count = await chat.app.client.get(
        f"{API}/specialists/count", params={"city_id": city}, headers=headers
    )
    assert (page.status_code, count.status_code) == (200, 200), page.text
    return [item["profile_id"] for item in page.json()["items"]], count.json()["count"]


async def test_blocked_specialist_is_not_in_search_either_way(chat: Chat) -> None:
    specialist, city = await listed_alone(chat)
    client, other = await chat.user(), await chat.user()
    mine = str(specialist.profile_id)
    assert await found(chat, client, city) == ([mine], 1)

    await block(chat, client, specialist.user_id)

    assert await found(chat, client, city) == ([], 0)
    assert await found(chat, other, city) == ([mine], 1)
    assert await found(chat, None, city) == ([mine], 1)  # гость
    blocks = await chat.get(client, "/me/blocks")
    [item] = blocks.json()["items"]
    assert (item["user_id"], item["profile_id"], item["display_name"]) == (
        str(specialist.user_id),
        mine,
        "Marko P.",
    )
    card = await chat.get(client, f"/specialists/{mine}")
    assert card.json()["user_id"] == str(specialist.user_id)  # «Заблокировать» на S08

    await unblock(chat, client, specialist.user_id)
    await block(chat, specialist.user_id, other)  # и в обратную сторону

    assert await found(chat, client, city) == ([mine], 1)
    assert await found(chat, other, city) == ([], 0)
    assert (await chat.get(other, "/me/blocks")).json()["items"] == []  # не его блокировка


async def test_blocked_specialist_leaves_favorites_until_unblocked(chat: Chat) -> None:
    specialist, _ = await listed_alone(chat)
    client = await chat.user()
    path = f"{API}/me/favorites/profile/{specialist.profile_id}"
    assert (await chat.app.client.put(path, headers=chat.headers(client))).status_code == 204

    await block(chat, specialist.user_id, client)
    hidden = await chat.get(client, "/me/favorites")
    await unblock(chat, specialist.user_id, client)
    back = await chat.get(client, "/me/favorites")

    assert hidden.json()["items"] == []
    assert [item["profile_id"] for item in back.json()["items"]] == [str(specialist.profile_id)]


async def own_job(chat: Chat, client: UserId, budget: int) -> UUID:
    """Опубликованная сейчас заявка с бюджетом, которого нет у других тестов: лента по нему."""
    job_id = await chat.job(client)
    await chat.execute(
        "UPDATE jobs.jobs SET budget_min = :budget, published_at = :now WHERE id = :id",
        budget=budget,
        now=datetime.now(UTC),
        id=job_id,
    )
    return job_id


async def test_blocked_clients_jobs_leave_the_feed_and_cannot_be_answered(chat: Chat) -> None:
    client, performer, other = await chat.user(), await chat.user(), await chat.user()
    budget = MAX_BUDGET - new_id().int % 1000  # выше бюджетов других тестов, но допустимый
    job_id = await own_job(chat, client, budget)
    city = await chat.scalar("SELECT id FROM geo.cities WHERE slug = 'novi-sad'")
    params = {"city_id": city, "budget_from": budget}

    async def feed(viewer: UserId) -> tuple[list[str], int]:
        page = await chat.get(viewer, f"/jobs?city_id={city}&budget_from={budget}")
        count = await chat.app.client.get(
            f"{API}/jobs/count", params=params, headers=chat.headers(viewer)
        )
        return [item["id"] for item in page.json()["items"]], count.json()["count"]

    assert await feed(performer) == ([str(job_id)], 1)
    await block(chat, client, performer)  # клиент заблокировал исполнителя

    assert await feed(performer) == ([], 0)
    assert await feed(other) == ([str(job_id)], 1)
    card = await chat.get(performer, f"/jobs/{job_id}")
    assert (card.status_code, card.json()["code"]) == (404, "job_not_found")
    assert (await chat.get(client, f"/jobs/{job_id}")).status_code == 200  # своя — видна
    reply = await chat.app.client.post(
        f"{API}/jobs/{job_id}/responses",
        json={
            "message": "Здравствуйте! Могу сегодня в 19:00.",
            "price_type": "fixed",
            "price_amount": 350_000,
            "availability_note": "Сегодня, 19:00",
        },
        headers=chat.headers(performer) | {"Idempotency-Key": new_id().hex},
    )
    assert (reply.status_code, reply.json()["code"]) == (404, "job_not_found")

    await unblock(chat, client, performer)
    assert await feed(performer) == ([str(job_id)], 1)


async def test_blocked_specialist_cannot_be_invited(chat: Chat) -> None:
    specialist, _ = await listed_alone(chat)
    client = await chat.user()
    job_id = await chat.job(client)
    await block(chat, specialist.user_id, client)

    invite = await chat.post(
        client, f"/jobs/{job_id}/invites", {"profile_ids": [str(specialist.profile_id)]}
    )

    assert (invite.status_code, invite.json()["code"]) == (404, "invitee_not_found")


async def test_blocked_pair_can_read_but_not_write(chat: Chat) -> None:
    specialist, _ = await listed_alone(chat)
    client = await chat.user()
    conversation = await chat.start(client, profile_id=str(specialist.profile_id))
    await chat.send(client, conversation, "Здравствуйте! Нужна люстра.")

    await block(chat, specialist.user_id, client)

    sent = await chat.post(client, f"/conversations/{conversation}/messages", {"body": "Ау?"})
    assert (sent.status_code, sent.json()["code"], sent.json()["conversation_status"]) == (
        409,
        "conversation_closed",
        "blocked",
    )
    mine = (await chat.messages(client, conversation))["conversation"]
    theirs = (await chat.messages(specialist.user_id, conversation))["conversation"]
    assert (mine["blocked"], mine["blocked_by_me"]) == (True, False)
    assert (theirs["blocked"], theirs["blocked_by_me"]) == (True, True)
    assert len((await chat.messages(client, conversation))["items"]) == 1  # история — читается
    again = await chat.post(client, "/conversations", {"profile_id": str(specialist.profile_id)})
    assert (again.status_code, again.json()["id"]) == (200, conversation)  # начатый — открыть
    stranger_chat = await chat.user()
    await block(chat, stranger_chat, specialist.user_id)
    fresh = await chat.post(
        stranger_chat, "/conversations", {"profile_id": str(specialist.profile_id)}
    )
    assert (fresh.status_code, fresh.json()["reason"]) == (409, "blocked")

    await unblock(chat, specialist.user_id, client)
    await chat.send(client, conversation, "Снова на связи")
    assert (await chat.mine(client))[conversation]["blocked"] is False


async def test_report_becomes_a_case_and_a_repeat_is_the_same_report(chat: Chat) -> None:
    specialist, _ = await listed_alone(chat)
    reporter = await chat.user()
    target = {"target_type": "profile", "target_id": str(specialist.profile_id)}

    first = await report(chat, reporter, **target, comment="Просит предоплату на карту")
    again = await report(chat, reporter, **target, reason="offensive")

    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["id"] == first.json()["id"]
    assert (first.json()["queue"], first.json()["status"]) == ("fraud", "open")
    [(queue, subject, trigger)] = await chat.rows(
        "SELECT queue, subject_id, trigger FROM moderation.cases WHERE entity_id = :id"
        " AND status = 'pending'",
        id=specialist.profile_id,
    )
    assert (queue, subject, trigger) == ("fraud", specialist.user_id, "report")
    own = await report(chat, specialist.user_id, **target)
    assert (own.status_code, own.json()["code"]) == (422, "invalid_report")
    wrong = await report(chat, reporter, **target, reason="no_show")
    assert (wrong.status_code, wrong.json()["field"]) == (422, "reason")
    gone = await report(chat, reporter, target_type="job", target_id=str(new_id()))
    assert (gone.status_code, gone.json()["code"]) == (404, "report_target_not_found")
    assert (await chat.app.client.post(f"{API}/reports", json=target)).status_code == 401


async def test_report_from_a_chat_and_the_twenty_first_a_day(chat: Chat) -> None:
    client, performer, response_id = await chat.pair()
    conversation = await chat.start(client, response_id=response_id)
    stranger = await chat.user()

    from_chat = await report(
        chat,
        client,
        target_type="user",
        target_id=str(performer),
        reason="no_show",
        conversation_id=conversation,
    )
    elsewhere = await report(
        chat,
        client,
        target_type="user",
        target_id=str(stranger),
        conversation_id=conversation,
    )

    assert from_chat.status_code == 201, from_chat.text
    assert (elsewhere.status_code, elsewhere.json()["field"]) == (422, "conversation_id")
    [(conversation_ref,)] = await chat.rows(
        "SELECT evidence -> 0 ->> 'conversation_id' FROM moderation.cases WHERE entity_id = :id"
        " AND status = 'pending'",
        id=performer,
    )
    assert conversation_ref == conversation
    for _ in range(19):  # первая жалоба уже засчитана
        filed = await report(chat, client, target_type="user", target_id=str(await chat.user()))
        assert filed.status_code == 201, filed.text
    over = await report(chat, client, target_type="user", target_id=str(stranger))
    assert (over.status_code, over.json()["code"]) == (429, "reports_limit")


async def test_blocked_performers_response_is_hidden_and_cannot_be_chosen(chat: Chat) -> None:
    client, performer, response_id = await chat.pair()
    job_id = await chat.scalar(
        "SELECT job_id FROM jobs.responses WHERE id = :id", id=UUID(response_id)
    )

    async def shown() -> tuple[list[str], list[str]]:
        cards = await chat.get(client, f"/jobs/{job_id}/response-cards")
        listed = await chat.get(client, f"/jobs/{job_id}/responses")
        assert (cards.status_code, listed.status_code) == (200, 200), cards.text
        return (
            [item["id"] for item in cards.json()["items"]],
            [item["id"] for item in listed.json()["items"]],
        )

    assert await shown() == ([response_id], [response_id])
    await block(chat, performer, client)  # исполнитель заблокировал клиента

    assert await shown() == ([], [])
    chosen = await chat.post(client, f"/responses/{response_id}/accept")
    assert (chosen.status_code, chosen.json()["code"]) == (404, "response_not_found")

    await unblock(chat, performer, client)
    assert await shown() == ([response_id], [response_id])
