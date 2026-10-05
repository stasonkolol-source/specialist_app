"""«Отзывы до платформы» (DEVELOPMENT_PLAN 7.6а; ADR-0016) через API: специалист с опубликованным
профилем создаёт до пяти ссылок прошлым клиентам и отзывает неиспользованные; по ссылке гость видит
форму S56, вошедший оставляет один отзыв — он ждёт модератора, на S11 появляется во вкладке «До
платформы» и в рейтинг не входит. Чужая, отозванная, истёкшая и использованная ссылка — 404, о себе
отзыв не оставить. Подписчики выполняются из очереди. Данные коммитятся.
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.entrypoints._wiring import make_worker_container, module_routers
from app.modules.identity.api import RestrictionKind
from app.modules.reviews.api import ReviewsApi
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings
from app.platform.telegram.deeplinks import LinkType, parse_start_param
from tests.plugins.chat import API, Chat
from tests.plugins.http import HttpApp, http_app
from tests.plugins.queue import run_queued
from tests.plugins.search import Specialist

pytestmark = pytest.mark.integration

INVITES = "/me/profile/review-invites"
FORM = {
    "rating": 5,
    "work_title": "Проводка в ванной и светильники",
    "body": "Поменял проводку в ванной и повесил светильники. Всё сделал за день.",
    "confirmed": True,
}


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


async def specialist_of(chat: Chat) -> tuple[Specialist, UserId]:
    specialist = Specialist(chat.app.container)
    await specialist.publish()
    await specialist.drop_jobs()  # проверка профиля и прочие подписчики публикации — не здесь
    chat.users.append(UserId(specialist.user_id))
    return specialist, UserId(specialist.user_id)


async def invite(chat: Chat, user: UserId, **body: Any) -> dict[str, Any]:
    reply = await chat.post(user, INVITES, body)
    assert reply.status_code == 201, reply.text
    created: dict[str, Any] = reply.json()
    return created


async def invites(chat: Chat, user: UserId) -> dict[str, Any]:
    reply = await chat.get(user, INVITES)
    assert reply.status_code == 200, reply.text
    found: dict[str, Any] = reply.json()
    return found


async def revoke(chat: Chat, user: UserId, token: str) -> Any:
    return await chat.app.client.delete(f"{API}{INVITES}/{token}", headers=chat.headers(user))


async def form(chat: Chat, token: str, user: UserId | None = None) -> Any:
    headers = chat.headers(user) if user is not None else {}
    return await chat.app.client.get(f"{API}/review-invites/{token}", headers=headers)


def error(reply: Any) -> tuple[int, str]:
    return reply.status_code, reply.json()["code"]


async def approve(chat: Chat, review_id: str) -> None:
    """Модератор одобрил отзыв (кейс из очереди): тот же фасад, что у решения модератора."""
    async with chat.app.container() as request:
        uow, reviews = await request.get(UnitOfWork), await request.get(ReviewsApi)
        async with uow:
            await reviews.approve_review(UUID(review_id))


async def test_specialist_keeps_five_invites_at_most_and_revokes_an_unused_one(
    chat: Chat,
) -> None:
    _, performer = await specialist_of(chat)
    first = await invite(chat, performer, client_name="  Андрей В. ")
    assert (first["client_name"], first["status"]) == ("Андрей В.", "waiting")
    link = parse_start_param(first["start_param"])
    assert link is not None
    assert link.type is LinkType.REVIEW_INVITE
    assert link.id == UUID(first["token"])
    assert first["url"].startswith("https://t.me/")
    assert first["url"].endswith(f"?startapp={first['start_param']}")
    for _ in range(4):
        await invite(chat, performer)
    sixth = await chat.post(performer, INVITES, {})
    assert error(sixth) == (409, "review_invites_full")
    assert sixth.json()["limit"] == 5

    listed = await invites(chat, performer)
    assert (listed["taken"], listed["limit"], len(listed["items"])) == (5, 5, 5)
    assert listed["items"][-1]["token"] == first["token"]  # новые первыми
    assert (await revoke(chat, performer, first["token"])).status_code == 204
    assert (await form(chat, first["token"])).status_code == 404
    assert (await invites(chat, performer))["taken"] == 4
    await invite(chat, performer)  # место освободилось

    # истёкшая ссылка тоже освобождает место и не открывается
    await chat.execute(
        "UPDATE reviews.review_invites SET expires_at = now() - interval '1 minute'"
        " WHERE token = :token",
        token=UUID(listed["items"][0]["token"]),
    )
    after = await invites(chat, performer)
    assert after["taken"] == 4
    assert after["items"][1]["status"] == "expired"
    assert (await form(chat, listed["items"][0]["token"])).status_code == 404

    nobody = await chat.user()
    refused = await chat.post(nobody, INVITES, {})
    assert error(refused) == (409, "review_invites_unavailable")
    assert (await invites(chat, nobody)) == {"items": [], "limit": 5, "taken": 0}


async def test_posting_block_stops_new_invites(chat: Chat) -> None:
    """SEC-01: под санкцией на публикацию новых ссылок нет — 403 `restricted`, как у правок
    профиля и прайса; выданные раньше остаются."""
    specialist, user = await specialist_of(chat)
    before = await invite(chat, user, client_name="Ана")
    await specialist.restrict(RestrictionKind.POSTING_BLOCKED, None)

    refused = await chat.post(user, INVITES, {"client_name": "Марко"})

    assert error(refused) == (403, "restricted")
    assert refused.json()["restriction"] == "posting_blocked"
    assert [item["token"] for item in (await invites(chat, user))["items"]] == [before["token"]]


async def test_past_client_review_is_labelled_moderated_and_outside_the_rating(
    chat: Chat, worker: AsyncContainer
) -> None:
    specialist, performer = await specialist_of(chat)
    token = (await invite(chat, performer))["token"]

    guest = await form(chat, token)
    assert guest.status_code == 200, guest.text
    shown = guest.json()
    assert shown["specialist"]["profile_id"] == str(specialist.profile_id)
    assert shown["specialist"]["first_name"] == shown["specialist"]["display_name"].split()[0]
    assert shown["specialist"]["headline"] == "Электрик, 10 лет"
    assert [c["id"] for c in shown["specialist"]["categories"]] == [specialist.category]
    assert shown["is_own"] is False
    assert guest.headers["cache-control"] == "private, no-store"
    assert (await form(chat, token, performer)).json()["is_own"] is True

    client = await chat.user()
    anonymous = await chat.app.client.post(f"{API}/review-invites/{token}", json=FORM)
    assert anonymous.status_code == 401
    unconfirmed = await chat.post(client, f"/review-invites/{token}", FORM | {"confirmed": False})
    assert unconfirmed.status_code == 422
    created = await chat.post(client, f"/review-invites/{token}", FORM)
    assert created.status_code == 201, created.text
    review = created.json()
    assert (review["kind"], review["status"], review["deal_id"]) == (
        "pre_platform",
        "under_review",
        None,
    )
    assert review["work_title"] == FORM["work_title"]

    # ссылка использована: второй отзыв по ней не принять, форма не открывается
    other = await chat.user()
    assert error(await chat.post(other, f"/review-invites/{token}", FORM)) == (
        404,
        "review_invite_not_found",
    )
    assert (await form(chat, token)).status_code == 404
    assert error(await revoke(chat, performer, token)) == (409, "review_invite_used")

    # автопроверка не публикует: «до платформы» всегда смотрит модератор
    assert await run_queued(worker, "moderation.auto_check", user_id=client, by="author_id") == 1
    status = await chat.scalar(
        "SELECT status FROM reviews.reviews WHERE id = :id", id=UUID(review["id"])
    )
    assert status == "under_review"
    cases = await chat.scalar(
        "SELECT count(*) FROM moderation.cases WHERE entity_type = 'review' AND entity_id = :id",
        id=UUID(review["id"]),
    )
    assert cases == 1
    [item] = (await invites(chat, performer))["items"]
    assert (item["status"], item["reviewer_name"], item["rating"]) == ("under_review", "Ana", 5)

    await approve(chat, review["id"])
    # события публикации нет: рейтинг не пересчитывается, review rate и уведомление его не видят
    assert (
        await run_queued(
            worker, "reviews.recompute_on_published", user_id=performer, by="subject_user_id"
        )
        == 0
    )
    assert (
        await chat.scalar(
            "SELECT count(*) FROM reviews.rating_aggregates WHERE subject_profile_id = :id",
            id=specialist.profile_id,
        )
        == 0
    )

    deals_tab = await chat.get(client, f"/specialists/{specialist.profile_id}/reviews")
    assert deals_tab.status_code == 200, deals_tab.text
    body = deals_tab.json()
    assert (body["items"], body["pre_platform_count"]) == ([], 1)
    assert (body["summary"]["count"], body["summary"]["is_new"]) == (0, True)
    card = await chat.get(client, f"/specialists/{specialist.profile_id}")
    assert card.json()["reviews"] == []  # S08 — только отзывы по сделкам
    tab = await chat.get(client, f"/specialists/{specialist.profile_id}/reviews?kind=pre_platform")
    [shown_review] = tab.json()["items"]
    assert (shown_review["kind"], shown_review["work_title"]) == (
        "pre_platform",
        FORM["work_title"],
    )
    assert (shown_review["author_name"], shown_review["category"]) == ("Ana", None)
    [published] = (await invites(chat, performer))["items"]
    assert published["status"] == "published"
    assert published["published_at"] is not None
    [mine] = (await chat.get(client, "/me/reviews?direction=written")).json()["items"]
    assert (mine["kind"], mine["work_title"]) == ("pre_platform", FORM["work_title"])


@pytest.mark.authz
async def test_authz_strangers_cannot_revoke_and_nobody_reviews_himself_or_twice(
    chat: Chat,
) -> None:
    _, performer = await specialist_of(chat)
    _, stranger = await specialist_of(chat)
    token = (await invite(chat, performer))["token"]

    # чужую ссылку не отозвать: для чужого она «не найдена»
    assert error(await revoke(chat, stranger, token)) == (404, "review_invite_not_found")
    assert (await form(chat, token)).status_code == 200
    # о себе по своей ссылке — нет
    own = await chat.post(performer, f"/review-invites/{token}", FORM)
    assert error(own) == (409, "own_profile_review")
    # несуществующая ссылка — то же 404, что отозванная и использованная
    unknown = str(new_id())
    assert (await form(chat, unknown)).status_code == 404
    assert error(await chat.post(stranger, f"/review-invites/{unknown}", FORM)) == (
        404,
        "review_invite_not_found",
    )
    assert error(await revoke(chat, performer, unknown)) == (404, "review_invite_not_found")

    # один отзыв до платформы от человека на профиль, даже по второй ссылке
    client = await chat.user()
    created = await chat.post(client, f"/review-invites/{token}", FORM)
    assert created.status_code == 201, created.text
    second = (await invite(chat, performer))["token"]
    again = await chat.post(client, f"/review-invites/{second}", FORM)
    assert error(again) == (409, "pre_platform_review_exists")
    assert (await form(chat, second)).status_code == 200  # ссылка осталась свободной

    # профиль скрыт из каталога — ссылка не открывается, отзыв по ней не принять
    hidden = await chat.post(performer, "/me/profile/hide")
    assert hidden.status_code == 200, hidden.text
    assert (await form(chat, second)).status_code == 404
    late = await chat.user()
    assert error(await chat.post(late, f"/review-invites/{second}", FORM)) == (
        404,
        "review_invite_not_found",
    )
