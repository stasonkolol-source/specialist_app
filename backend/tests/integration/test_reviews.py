"""Отзывы по сделкам (DEVELOPMENT_PLAN 7.2) через API: отзыв оставляет только клиент по
завершённой сделке и не позже 14 дней (иначе 409), один раз; он виден на карточке специалиста
после автопроверки, рейтинг пересчитывается и попадает в выдачу; специалист отвечает один раз,
ответ виден после своей проверки; снятый отзыв убирает рейтинг. Подписчики выполняются из
очереди. Данные коммитятся.
"""

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

import pytest
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.entrypoints._wiring import make_worker_container, module_routers
from app.modules.reviews.api import ReviewsApi
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings
from tests.plugins.chat import Chat
from tests.plugins.http import HttpApp, http_app
from tests.plugins.queue import run_queued
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


async def agreed_deal(chat: Chat) -> tuple[Specialist, UserId, str]:
    """Клиент договорился со специалистом в прямом диалоге (6.3b)."""
    specialist = Specialist(chat.app.container)
    await specialist.publish()
    chat.users.append(UserId(specialist.user_id))
    client = await chat.user()
    conversation_id = await chat.start(client, profile_id=str(specialist.profile_id))
    proposed = await chat.post(
        client, f"/conversations/{conversation_id}/deal", {"title": "Повесить люстру"}
    )
    assert proposed.status_code == 201, proposed.text
    deal_id: str = proposed.json()["deal_id"]
    confirmed = await chat.post(UserId(specialist.user_id), f"/deals/{deal_id}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    await specialist.drop_jobs()  # проверка профиля и прочие подписчики публикации — не здесь
    return specialist, client, deal_id


async def complete(chat: Chat, deal_id: str, *users: UserId) -> None:
    for user in users:
        marked = await chat.post(user, f"/deals/{deal_id}/complete")
        assert marked.status_code == 200, marked.text


async def card(chat: Chat, user: UserId, deal_id: str) -> Any:
    reply = await chat.get(user, f"/deals/{deal_id}/card")
    assert reply.status_code == 200, reply.text
    return reply.json()


async def profile_reviews(chat: Chat, user: UserId, specialist: Specialist) -> Any:
    reply = await chat.get(user, f"/specialists/{specialist.profile_id}/reviews")
    assert reply.status_code == 200, reply.text
    return reply.json()


async def mine(chat: Chat, user: UserId, direction: str) -> list[Any]:
    reply = await chat.get(user, f"/me/reviews?direction={direction}")
    assert reply.status_code == 200, reply.text
    items: list[Any] = reply.json()["items"]
    return items


async def checked(worker: AsyncContainer, author: UserId) -> None:
    """Автопроверка (moderation.auto_check) пропускает чистый текст."""
    assert await run_queued(worker, "moderation.auto_check", user_id=author, by="author_id") == 1


async def recomputed(worker: AsyncContainer, specialist: Specialist, task: str) -> None:
    subject = specialist.user_id
    assert await run_queued(worker, task, user_id=subject, by="subject_user_id") == 1


def error(reply: Any) -> tuple[int, str, str | None]:
    body = reply.json()
    return reply.status_code, body["code"], body.get("reason")


async def test_review_after_the_deal_is_published_rated_and_ranked(
    chat: Chat, worker: AsyncContainer
) -> None:
    specialist, client, deal_id = await agreed_deal(chat)
    performer = UserId(specialist.user_id)

    early = await chat.post(client, f"/deals/{deal_id}/review", {"rating": 5})
    assert error(early) == (409, "review_not_allowed", "not_completed")
    assert (await card(chat, client, deal_id))["review_until"] is None

    await complete(chat, deal_id, client, performer)
    done = await card(chat, client, deal_id)
    completed_at = datetime.fromisoformat(done["timeline"]["completed_at"])
    assert datetime.fromisoformat(done["review_until"]) == completed_at + timedelta(days=14)
    assert (await card(chat, performer, deal_id))["review_until"] is None  # отзыв пишет клиент
    by_performer = await chat.post(performer, f"/deals/{deal_id}/review", {"rating": 5})
    assert error(by_performer) == (409, "review_not_allowed", "not_client")

    created = await chat.post(
        client,
        f"/deals/{deal_id}/review",
        {"rating": 5, "criteria": {"quality": 5, "punctuality": 4}, "body": "Быстро и аккуратно"},
    )
    assert created.status_code == 201, created.text
    review = created.json()
    assert (review["status"], review["rating"]) == ("under_review", 5)
    assert review["criteria"] == {"quality": 5, "punctuality": 4}
    again = await chat.post(client, f"/deals/{deal_id}/review", {"rating": 1})
    assert error(again) == (409, "review_exists", None)
    waiting = await card(chat, client, deal_id)
    assert waiting["my_review"] == {"id": review["id"], "status": "under_review", "rating": 5}
    assert waiting["review_until"] is None
    assert (await profile_reviews(chat, client, specialist))["items"] == []

    await checked(worker, client)
    await recomputed(worker, specialist, "reviews.recompute_on_published")

    listed = await profile_reviews(chat, client, specialist)
    [shown] = listed["items"]
    assert (shown["id"], shown["body"], shown["rating"]) == (review["id"], "Быстро и аккуратно", 5)
    assert shown["criteria"] == {"quality": 5, "punctuality": 4}
    assert shown["reply"] is None
    summary = listed["summary"]
    assert (summary["count"], summary["is_new"]) == (1, True)
    assert summary["distribution"] == [0, 0, 0, 0, 1]
    assert summary["criteria"] == {"punctuality": 4.0, "quality": 5.0}
    s08 = (await chat.get(client, f"/specialists/{specialist.profile_id}")).json()
    assert [r["id"] for r in s08["reviews"]] == [review["id"]]
    assert s08["rating_count"] == 1
    [written] = await mine(chat, client, "written")
    assert (written["status"], written["deal_title"]) == ("published", "Повесить люстру")

    rating_changed = await run_queued(
        worker, "search.on_rating_changed", user_id=specialist.profile_id, by="profile_id"
    )
    assert rating_changed == 1
    await specialist.flush()
    row = await specialist.row()
    assert row is not None
    assert row["rating_count"] == 1
    assert 4.6 < float(row["rating_bayes"]) < 5.0  # одна «пятёрка» — не 5,0
    assert 2.05 < float(row["rating_lower_bound"]) < 3.0  # выше профиля без отзывов

    async with worker() as request:
        uow, reviews = await request.get(UnitOfWork), await request.get(ReviewsApi)
        async with uow:
            await reviews.reject_review(review["id"], reason_code="spam")
    await recomputed(worker, specialist, "reviews.recompute_on_removed")
    assert (await profile_reviews(chat, client, specialist))["summary"]["count"] == 0
    removed = await card(chat, client, deal_id)
    assert removed["my_review"]["status"] == "removed"
    assert removed["review_until"] is None  # второй отзыв не написать


async def test_window_closes_fourteen_days_after_completion(chat: Chat) -> None:
    specialist, client, deal_id = await agreed_deal(chat)
    await complete(chat, deal_id, client, UserId(specialist.user_id))
    await chat.execute(
        "UPDATE deals.deals SET completed_at = now() - interval '15 days' WHERE id = :id",
        id=deal_id,
    )

    late = await chat.post(client, f"/deals/{deal_id}/review", {"rating": 4})

    assert error(late) == (409, "review_not_allowed", "window_closed")
    assert (await card(chat, client, deal_id))["review_until"] is None


async def test_specialist_replies_once_and_the_reply_shows_after_its_check(
    chat: Chat, worker: AsyncContainer
) -> None:
    specialist, client, deal_id = await agreed_deal(chat)
    performer = UserId(specialist.user_id)
    await complete(chat, deal_id, client, performer)
    created = await chat.post(client, f"/deals/{deal_id}/review", {"rating": 4, "body": "Хорошо"})
    review_id = created.json()["id"]
    early = await chat.post(performer, f"/reviews/{review_id}/reply", {"body": "Спасибо!"})
    assert error(early) == (404, "review_not_found", None)  # ещё не опубликован
    await checked(worker, client)

    stranger = await chat.user()
    for outsider in (stranger, client):
        refused = await chat.post(outsider, f"/reviews/{review_id}/reply", {"body": "Спасибо!"})
        assert error(refused) == (403, "not_review_subject", None)
    [received] = await mine(chat, performer, "received")
    assert received["can_reply"] is True

    replied = await chat.post(performer, f"/reviews/{review_id}/reply", {"body": " Спасибо! "})
    assert replied.status_code == 201, replied.text
    assert replied.json()["reply"]["status"] == "under_review"
    second = await chat.post(performer, f"/reviews/{review_id}/reply", {"body": "И ещё"})
    assert error(second) == (409, "reply_exists", None)
    [shown] = (await profile_reviews(chat, client, specialist))["items"]
    assert shown["reply"] is None  # до проверки не виден
    [received] = await mine(chat, performer, "received")
    assert (received["reply"]["status"], received["can_reply"]) == ("under_review", False)
    [written] = await mine(chat, client, "written")
    assert written["reply"] is None  # автор видит только прошедший проверку

    await checked(worker, performer)

    [shown] = (await profile_reviews(chat, client, specialist))["items"]
    assert shown["reply"]["body"] == "Спасибо!"
    [written] = await mine(chat, client, "written")
    assert written["reply"]["body"] == "Спасибо!"
    assert written["counterpart_name"]
