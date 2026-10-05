"""Заявки клиента (DEVELOPMENT_PLAN 5.1a) через API и конвейер модерации: создаётся сразу на
проверку и до публикации видна только владельцу; чистую публикует автопроверка, гость видит её
без точной точки и адреса; с контактами — в P2, после отказа клиент правит и снова на проверку;
If-Match, три продления, лимиты новичка и проверенного, удаление аккаунта. Данные коммитятся.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from dishka import AsyncContainer, Provider, Scope, provide
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._wiring import make_container, make_worker_container, module_routers
from app.entrypoints.seeds import load_city_seeds
from app.modules.jobs.application.use_cases.forget_client_jobs import (
    ForgetClientJobs,
    ForgetClientJobsCommand,
)
from app.modules.moderation.application.use_cases.auto_check import AutoCheck, AutoCheckCommand
from app.modules.moderation.application.use_cases.decide_case import (
    DecideCase,
    DecideCaseCommand,
)
from app.modules.moderation.domain.cases import EntityType
from app.modules.moderation.domain.pipeline import Route, Routing
from app.modules.moderation.domain.queues import Queue
from app.modules.moderation.errors import CaseSupersededError
from app.platform.ai.port import Moderation, PolicyClassifier
from app.platform.ai.stubs import NoModeration, NoPolicyClassifier
from app.platform.contracts.events.moderation import ModerationDecision
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings
from app.platform.telegram.deeplinks import LinkType, StartLink, encode_start_param
from tests.plugins.http import HttpApp, bearer, http_app
from tests.plugins.identity import accept_rules, insert_user
from tests.plugins.queue import run_queued

pytestmark = pytest.mark.integration

API = "/api/v1"
ADDRESS = "Народног фронта 12, улаз 2, стан 5"


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


class NoAiKeys(Provider):
    """Stage и прод без ключей AI (K25, K26 — после MVP): те адаптеры, что выбирает
    `platform/di.py::_stubs_allowed` вне dev и тестов."""

    scope = Scope.APP
    moderation = provide(NoModeration, provides=Moderation)
    classifier = provide(NoPolicyClassifier, provides=PolicyClassifier)


@pytest.fixture
async def worker_without_ai(storage_settings: Settings) -> AsyncIterator[AsyncContainer]:
    container = make_container(storage_settings, NoAiKeys())
    try:
        assert isinstance(await container.get(Moderation), NoModeration)
        assert isinstance(await container.get(PolicyClassifier), NoPolicyClassifier)
        yield container
    finally:
        await container.close()


async def rows(container: AsyncContainer, sql: str, **params: object) -> list[Any]:
    engine = await container.get(AsyncEngine)
    async with engine.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def scalar(container: AsyncContainer, sql: str, **params: object) -> Any:
    engine = await container.get(AsyncEngine)
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).scalar()


@pytest.fixture
async def body(web: HttpApp) -> dict[str, Any]:
    """Заявка в Лимане 3: обычная услуга (риск 0), бюджет 5 000 RSD, точка и адрес. Текст у
    каждого теста свой: один текст от трёх аккаунтов за сутки velocity считает рассылкой."""
    liman = next(d for s in load_city_seeds() for d in s.districts if d.slug == "liman-3")
    mark = "".join(chr(ord("a") + int(digit, 16)) for digit in new_id().hex[-12:])
    return {
        "title": "Повесить люстру в спальне",
        "description": f"Люстра на пять рожков, потолок 2,7 м, крюк уже есть. Метка {mark}.",
        "category_id": await scalar(
            web.container,
            "SELECT min(id) FROM catalog.categories WHERE is_active AND jobs_enabled"
            " AND risk_level = 0 AND parent_id IS NOT NULL",
        ),
        "urgency": "this_week",
        "budget_type": "fixed",
        "budget_min": 500_000,
        "city_id": await scalar(web.container, "SELECT id FROM geo.cities WHERE slug = 'novi-sad'"),
        "point": {"lat": liman.center.lat, "lon": liman.center.lon},
        "address_private": ADDRESS,
    }


class Client:
    """Клиент Mini App с токеном своего уровня доверия."""

    def __init__(self, app: HttpApp, headers: dict[str, str], user_id: UserId) -> None:
        self.app, self.headers, self.user_id = app, headers, user_id

    async def create(self, body: dict[str, Any], *, key: str | None = None) -> httpx.Response:
        headers = self.headers | {"Idempotency-Key": key or new_id().hex}
        return await self.app.client.post(f"{API}/jobs", json=body, headers=headers)

    async def created(self, body: dict[str, Any]) -> dict[str, Any]:
        response = await self.create(body)
        assert response.status_code == 201, response.text
        job: dict[str, Any] = response.json()
        return job

    async def get(self, job_id: str) -> httpx.Response:
        return await self.app.client.get(f"{API}/jobs/{job_id}", headers=self.headers)

    async def edit(self, job_id: str, body: dict[str, Any], etag: str) -> httpx.Response:
        headers = self.headers | {"If-Match": etag}
        return await self.app.client.patch(f"{API}/jobs/{job_id}", json=body, headers=headers)

    async def close(self, job_id: str, reason: str = "not_needed") -> httpx.Response:
        return await self.app.client.post(
            f"{API}/jobs/{job_id}/close", json={"reason": reason}, headers=self.headers
        )

    async def extend(self, job_id: str) -> httpx.Response:
        return await self.app.client.post(f"{API}/jobs/{job_id}/extend", headers=self.headers)

    async def delete(self, job_id: str) -> httpx.Response:
        return await self.app.client.delete(f"{API}/jobs/{job_id}", headers=self.headers)

    async def mine(self, *statuses: str) -> list[str]:
        response = await self.app.client.get(
            f"{API}/me/jobs", params=[("status", s) for s in statuses], headers=self.headers
        )
        assert response.status_code == 200, response.text
        return [job["id"] for job in response.json()["items"]]


@pytest.fixture
async def clients(web: HttpApp, storage_settings: Settings) -> AsyncIterator[list[Client]]:
    """Пользователи теста; их задачи в очереди (автопроверка, события) тест не выполняет."""
    created: list[Client] = []
    yield created
    engine = await web.container.get(AsyncEngine)
    async with engine.begin() as conn:
        for client in created:
            await conn.execute(
                text(
                    "DELETE FROM procrastinate_jobs WHERE status = 'todo' AND args::text LIKE :id"
                ),
                {"id": f"%{client.user_id}%"},
            )


async def new_client(
    web: HttpApp, settings: Settings, clients: list[Client], *, trust_level: int = 0
) -> Client:
    """Пользователь, принявший правила (S02c), — иначе создавать заявки нельзя."""
    async with web.container() as request:
        session = await request.get(AsyncSession)
        user_id = await insert_user(session)
        await accept_rules(session, user_id)
    client = Client(web, bearer(settings, user_id, trust_level=trust_level), user_id)
    clients.append(client)
    return client


async def auto_check(worker: AsyncContainer, client: Client, job_id: str) -> Routing:
    async with worker() as request:
        routing = await (await request.get(AutoCheck))(
            AutoCheckCommand(
                entity_type=EntityType.JOB, entity_id=UUID(job_id), author_id=client.user_id
            )
        )
    assert routing is not None
    return routing


async def published(worker: AsyncContainer, client: Client, body: dict[str, Any]) -> str:
    job = await client.created(body)
    assert (await auto_check(worker, client, job["id"])).route is Route.PUBLISH
    return str(job["id"])


def moment(value: str) -> datetime:
    return datetime.fromisoformat(value)


@pytest.mark.authz
async def test_new_job_waits_for_review_and_only_the_owner_sees_it(
    web: HttpApp, storage_settings: Settings, clients: list[Client], body: dict[str, Any]
) -> None:
    me = await new_client(web, storage_settings, clients)
    key = new_id().hex

    created = await me.create(body, key=key)

    assert created.status_code == 201, created.text
    job = created.json()
    assert (job["status"], job["viewer_role"]) == ("pending_moderation", "owner")
    assert (job["point_exact"], job["address_private"]) == (body["point"], ADDRESS)
    assert job["point_public"] not in (None, body["point"])  # смещена на 300–500 м
    district = await scalar(web.container, "SELECT id FROM geo.districts WHERE slug = 'liman-3'")
    assert job["district_id"] == district  # район — по точке
    assert job["budget_min"] == {"amount": 500_000, "currency": "RSD"}
    assert created.headers["ETag"] == f'"{job["version"]}"'
    again = await me.create(body, key=key)
    assert (again.json()["id"], again.headers.get("Idempotency-Replayed")) == (job["id"], "true")
    assert await me.mine() == [job["id"]]
    assert await me.mine("published") == []

    stranger = await new_client(web, storage_settings, clients)
    assert (await stranger.get(job["id"])).status_code == 404
    guest = await web.client.get(f"{API}/jobs/{job['id']}")
    assert (guest.status_code, guest.json()["code"]) == (404, "job_not_found")
    assert (await web.client.post(f"{API}/jobs", json=body)).status_code == 401


async def test_clean_job_is_published_and_guests_do_not_see_the_address(
    web: HttpApp,
    worker: AsyncContainer,
    storage_settings: Settings,
    clients: list[Client],
    body: dict[str, Any],
) -> None:
    me = await new_client(web, storage_settings, clients)
    job_id = await published(worker, me, body)

    seen = await web.client.get(f"{API}/jobs/{job_id}")

    assert seen.status_code == 200, seen.text
    public = seen.json()
    assert (public["status"], public["viewer_role"]) == ("published", "viewer")
    assert (public["point_exact"], public["address_private"]) == (None, None)
    assert public["point_public"] is not None
    assert "ETag" not in seen.headers
    # «на этой неделе» — 7 дней с публикации (§7.9)
    assert moment(public["expires_at"]) - moment(public["published_at"]) == timedelta(days=7)
    own = (await me.get(job_id)).json()
    assert (own["viewer_role"], own["address_private"]) == ("owner", ADDRESS)
    assert await me.mine("published") == [job_id]


async def test_job_with_contacts_waits_for_a_moderator_and_goes_back_after_fixes(
    web: HttpApp,
    worker: AsyncContainer,
    storage_settings: Settings,
    clients: list[Client],
    body: dict[str, Any],
) -> None:
    me = await new_client(web, storage_settings, clients)
    leaking = body | {"description": "Люстра на пять рожков. Звоните: +381 64 123 4567"}
    job = await me.created(leaking)

    routing = await auto_check(worker, me, job["id"])

    assert (routing.route, routing.queue) == (Route.REVIEW, Queue.PREMOD)
    assert (await me.get(job["id"])).json()["status"] == "pending_moderation"
    case_id = await scalar(
        web.container,
        "SELECT id FROM moderation.cases WHERE entity_id = :id AND status = 'pending'",
        id=UUID(job["id"]),
    )
    async with worker() as request:
        await (await request.get(DecideCase))(
            DecideCaseCommand(
                case_id=case_id, verdict=ModerationDecision.REJECTED, reason_code="contact_leak"
            )
        )
    rejected = await me.get(job["id"])
    assert (rejected.json()["status"], rejected.json()["moderation_note"]) == (
        "rejected",
        "contact_leak",
    )
    # гостю отклонённая не видна, причину видит только владелец
    assert (await web.client.get(f"{API}/jobs/{job['id']}")).status_code == 404

    fixed = await me.edit(job["id"], body, rejected.headers["ETag"])

    assert fixed.status_code == 200, fixed.text
    assert (fixed.json()["status"], fixed.json()["moderation_note"]) == ("pending_moderation", None)


async def test_without_ai_keys_clean_job_is_published_at_once(
    web: HttpApp,
    worker_without_ai: AsyncContainer,
    storage_settings: Settings,
    clients: list[Client],
    body: dict[str, Any],
) -> None:
    """Ворота беты 2.2 (ключи AI — после MVP): чистую заявку новичка стоп-правила публикуют
    сразу, заявка с телефоном ждёт модератора, как и с ключами."""
    me = await new_client(web, storage_settings, clients)

    job_id = await published(worker_without_ai, me, body)
    phone = {"description": f"{body['description']} Звоните: +381 64 123 4567"}
    leaking = await me.created(body | phone)
    routing = await auto_check(worker_without_ai, me, leaking["id"])

    assert (await me.get(job_id)).json()["status"] == "published"
    assert (routing.route, routing.queue) == (Route.REVIEW, Queue.PREMOD)
    assert not any("no_key" in signal for signal in routing.signals)


@pytest.mark.authz
async def test_stale_version_is_refused_and_strangers_cannot_touch_the_job(
    web: HttpApp, storage_settings: Settings, clients: list[Client], body: dict[str, Any]
) -> None:
    me = await new_client(web, storage_settings, clients)
    created = await me.create(body)
    job_id, etag = created.json()["id"], created.headers["ETag"]

    edited = await me.edit(job_id, body | {"title": "Повесить две люстры"}, etag)
    assert edited.status_code == 200, edited.text
    assert edited.json()["title"] == "Повесить две люстры"
    assert edited.headers["ETag"] != etag
    stale = await me.edit(job_id, body, etag)
    assert (stale.status_code, stale.json()["code"]) == (412, "stale_version")

    stranger = await new_client(web, storage_settings, clients)
    for response in (
        await stranger.edit(job_id, body, edited.headers["ETag"]),
        await stranger.close(job_id),
        await stranger.extend(job_id),
        await stranger.delete(job_id),
    ):
        assert (response.status_code, response.json()["code"]) == (404, "job_not_found")
    assert (await me.get(job_id)).json()["status"] == "pending_moderation"


async def test_edits_in_a_row_keep_their_etag_across_auto_moderation(
    web: HttpApp,
    worker: AsyncContainer,
    storage_settings: Settings,
    clients: list[Client],
    body: dict[str, Any],
) -> None:
    """ADV-07: автопроверка публикует заявку после создания и после правки — ETag клиента от
    этого не устаревает: и первая правка с ETag ответа на создание, и вторая подряд — 200."""
    me = await new_client(web, storage_settings, clients)
    created = await me.create(body)
    job_id, etag = created.json()["id"], created.headers["ETag"]
    assert (await auto_check(worker, me, job_id)).route is Route.PUBLISH

    first = await me.edit(job_id, body | {"title": "Повесить две люстры"}, etag)
    assert first.status_code == 200, first.text
    assert first.json()["version"] == int(first.headers["ETag"].strip('"'))
    assert (await auto_check(worker, me, job_id)).route is Route.PUBLISH
    second = await me.edit(job_id, body | {"title": "Повесить три люстры"}, first.headers["ETag"])

    assert second.status_code == 200, second.text
    assert (await me.get(job_id)).headers["ETag"] == second.headers["ETag"]
    assert (await auto_check(worker, me, job_id)).route is Route.PUBLISH
    published_job = (await me.get(job_id)).json()
    assert (published_job["status"], published_job["title"]) == ("published", "Повесить три люстры")


async def case_of(container: AsyncContainer, job_id: str) -> Any:
    return await scalar(
        container,
        "SELECT id FROM moderation.cases WHERE entity_id = :id"
        " AND status IN ('pending', 'in_review', 'escalated')",
        id=UUID(job_id),
    )


async def decide(worker: AsyncContainer, case_id: Any) -> None:
    async with worker() as request:
        await (await request.get(DecideCase))(
            DecideCaseCommand(case_id=case_id, verdict=ModerationDecision.APPROVED)
        )


async def test_client_hears_only_about_a_publication_after_manual_review(
    web: HttpApp,
    worker: AsyncContainer,
    storage_settings: Settings,
    clients: list[Client],
    body: dict[str, Any],
) -> None:
    """UX-аудит №11 (G-A): заявку с телефоном опубликовал модератор — клиенту «Заявка
    опубликована» с кнопкой к ней; чистую публикует автопроверка за миллисекунды — S21 видит это
    сам, и в бот ничего не уходит."""
    me = await new_client(web, storage_settings, clients)
    await published(worker, me, body)  # чистая: автопроверка
    leaking = await me.created(body | {"description": "Люстра. Звоните: +381 64 123 4567"})
    assert (await auto_check(worker, me, leaking["id"])).queue is Queue.PREMOD

    await decide(worker, await case_of(web.container, leaking["id"]))

    task = "notifications.notify_job_published"
    assert await run_queued(worker, task, user_id=me.user_id, by="client_id") == 2  # обе
    notices = await rows(
        web.container,
        "SELECT type, payload FROM notifications.notifications WHERE user_id = :user",
        user=me.user_id,
    )
    link = encode_start_param(StartLink(type=LinkType.JOB, id=UUID(leaking["id"])))
    assert [(row.type, row.payload["link"]) for row in notices] == [("job.published", link)]


@pytest.mark.parametrize("checked", [True, False], ids=["edit_checked", "decision_first"])
async def test_moderator_publishes_only_the_version_the_card_showed(
    web: HttpApp,
    worker: AsyncContainer,
    storage_settings: Settings,
    clients: list[Client],
    body: dict[str, Any],
    checked: bool,
) -> None:
    """ADV-11: заявка с телефоном ждёт модератора; клиент меняет текст и бюджет после карточки.
    «Одобрить» по прежней карточке ничего не публикует — кейс устарел (правку проверила
    автопроверка или решение её опередило), а новый кейс показывает правку; его одобрение
    публикует ровно её."""
    me = await new_client(web, storage_settings, clients)
    seen = body | {"description": "Люстра на пять рожков. Звоните: +381 64 123 4567"}
    created = await me.create(seen)
    job_id = created.json()["id"]
    assert (await auto_check(worker, me, job_id)).queue is Queue.PREMOD
    stale_case = await case_of(web.container, job_id)
    swapped = body | {
        "title": "ПОДМЕНЁН после карточки",
        "description": "Пишите в телеграм @qa_contact_test",
        "budget_min": 9_900_000,
    }

    edited = await me.edit(job_id, swapped, created.headers["ETag"])
    assert edited.status_code == 200, edited.text
    if checked:
        await auto_check(worker, me, job_id)
    with pytest.raises(CaseSupersededError):
        await decide(worker, stale_case)

    assert (await me.get(job_id)).json()["status"] == "pending_moderation"
    assert (await web.client.get(f"{API}/jobs/{job_id}")).status_code == 404  # гостю не видна
    stale = await scalar(
        web.container, "SELECT reason_code FROM moderation.cases WHERE id = :id", id=stale_case
    )
    assert stale == "superseded"
    fresh_case = await case_of(web.container, job_id)
    assert fresh_case not in (None, stale_case)
    version = await scalar(
        web.container, "SELECT entity_version FROM moderation.cases WHERE id = :id", id=fresh_case
    )
    assert version == edited.json()["version"]  # новая карточка — о правке

    await decide(worker, fresh_case)

    public = (await web.client.get(f"{API}/jobs/{job_id}")).json()
    assert (public["status"], public["title"], public["description"]) == (
        "published",
        swapped["title"],
        swapped["description"],
    )
    assert public["budget_min"]["amount"] == swapped["budget_min"]


async def test_job_is_extended_three_times_at_most(
    web: HttpApp,
    worker: AsyncContainer,
    storage_settings: Settings,
    clients: list[Client],
    body: dict[str, Any],
) -> None:
    me = await new_client(web, storage_settings, clients)
    waiting = await me.created(body)
    early = await me.extend(waiting["id"])
    assert (early.status_code, early.json()["code"]) == (409, "job_not_open")
    job_id = await published(worker, me, body)

    for count in (1, 2, 3):
        extended = await me.extend(job_id)
        assert (extended.status_code, extended.json()["extensions_count"]) == (200, count)
    fourth = await me.extend(job_id)

    assert fourth.status_code == 409
    assert (fourth.json()["code"], fourth.json()["limit"]) == ("job_extend_limit", 3)


async def test_newcomer_keeps_three_active_jobs_and_five_new_a_day(
    web: HttpApp, storage_settings: Settings, clients: list[Client], body: dict[str, Any]
) -> None:
    me = await new_client(web, storage_settings, clients)
    ids = [(await me.created(body))["id"] for _ in range(3)]

    fourth = await me.create(body)

    assert (fourth.status_code, fourth.json()["code"]) == (429, "active_jobs_limit")
    assert fourth.headers["Retry-After"] == "3600"
    closed = await me.close(ids[0], "hired_elsewhere")
    assert (closed.json()["status"], closed.json()["close_reason"]) == ("closed", "hired_elsewhere")
    ids.append((await me.created(body))["id"])  # отказ по лимиту активных квоту не тратит
    assert (await me.delete(ids[1])).status_code == 204
    ids.append((await me.created(body))["id"])  # пятая за сутки
    assert (await me.close(ids[2])).status_code == 200
    sixth = await me.create(body)
    assert (sixth.status_code, sixth.json()["code"]) == (429, "daily_jobs_limit")
    assert sorted(await me.mine()) == sorted([ids[0], ids[2], ids[3], ids[4]])
    assert sorted(await me.mine("closed")) == sorted([ids[0], ids[2]])


@pytest.mark.parametrize("trust_level", [0, 1])
async def test_parallel_creations_take_only_the_last_active_place(
    web: HttpApp,
    storage_settings: Settings,
    clients: list[Client],
    body: dict[str, Any],
    trust_level: int,
) -> None:
    me = await new_client(web, storage_settings, clients, trust_level=trust_level)
    existing = [(await me.created(body))["id"] for _ in range(2)]

    replies = await asyncio.gather(*(me.create(body) for _ in range(5)))

    assert sorted(reply.status_code for reply in replies) == [201, 429, 429, 429, 429]
    assert {reply.json()["code"] for reply in replies if reply.status_code == 429} == {
        "active_jobs_limit"
    }
    assert len(await me.mine("pending_moderation")) == 3
    # Отказы по активным местам не тратят оставшиеся две заявки суточной квоты.
    for job_id in existing:
        assert (await me.close(job_id)).status_code == 200
        await me.created(body)


async def test_trusted_client_has_no_active_limit_but_twenty_new_a_day(
    web: HttpApp, storage_settings: Settings, clients: list[Client], body: dict[str, Any]
) -> None:
    me = await new_client(web, storage_settings, clients, trust_level=2)
    for _ in range(20):
        await me.created(body)

    over = await me.create(body)

    assert (over.status_code, over.json()["code"]) == (429, "daily_jobs_limit")


async def test_job_needs_an_open_category_and_a_point_in_the_city(
    web: HttpApp, storage_settings: Settings, clients: list[Client], body: dict[str, Any]
) -> None:
    me = await new_client(web, storage_settings, clients)
    root = await scalar(web.container, "SELECT max(id) FROM catalog.categories")
    belgrade = {"lat": 44.8125, "lon": 20.4612}

    unknown = await me.create(body | {"category_id": root + 1000})
    outside = await me.create(body | {"point": belgrade})
    negotiable = await me.create(body | {"budget_type": "negotiable"})

    assert (unknown.status_code, unknown.json()["code"]) == (422, "job_category_unavailable")
    assert (outside.status_code, outside.json()["code"]) == (422, "invalid_job")
    assert (outside.json()["field"], outside.json()["reason"]) == ("point", "outside_city")
    assert (negotiable.status_code, negotiable.json()["code"]) == (422, "invalid_job")
    assert await me.mine() == []


async def test_deleted_account_jobs_are_closed_and_the_address_forgotten(
    web: HttpApp,
    worker: AsyncContainer,
    storage_settings: Settings,
    clients: list[Client],
    body: dict[str, Any],
) -> None:
    me = await new_client(web, storage_settings, clients)
    open_id = await published(worker, me, body)
    deleted_id = (await me.created(body))["id"]
    assert (await me.delete(deleted_id)).status_code == 204

    async with worker() as request:
        forgotten = await (await request.get(ForgetClientJobs))(
            ForgetClientJobsCommand(user_id=me.user_id)
        )

    assert forgotten == 1  # удалённая раньше уже закрыта, её только забыть
    left = await scalar(
        web.container,
        "SELECT count(*) FROM jobs.jobs WHERE client_id = :user AND (deleted_at IS NULL"
        " OR status <> 'closed' OR point_exact IS NOT NULL OR address_private IS NOT NULL)",
        user=me.user_id,
    )
    assert left == 0
    assert (await web.client.get(f"{API}/jobs/{open_id}")).status_code == 404
