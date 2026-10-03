"""Споры по сделкам (DEVELOPMENT_PLAN 6.1c; ARCHITECTURE §14.4) через API и задачи воркера: спор
открывает кейс модерации P1 и будит вторую сторону, ответ и отзыв меняют спор, без ответа за
48 ч кейс помечается «нет ответа», решение модератора (`cli dispute-resolve`) переводит сделку и
уведомляет обе стороны, просмотр доказательств модератором (`cli dispute-show`) пишется в аудит,
удаление аккаунта стороны и очистка доказательств ждут, пока спор идёт. Данные коммитятся.
"""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._moderation_cli import dispute_resolve, dispute_show, moderation_decide
from app.entrypoints._wiring import make_worker_container, module_routers
from app.modules.deals.application.use_cases.sweep_disputes import (
    SweepDisputes,
    SweepDisputesCommand,
)
from app.modules.identity.application.use_cases.process_deletions import (
    ProcessDeletions,
    ProcessDeletionsCommand,
)
from app.modules.media.api import LegalHold
from app.platform.kernel.ids import MediaId, UserId, new_id
from app.platform.settings import Settings
from app.platform.telegram.deeplinks import LinkType, StartLink, encode_start_param
from tests.plugins.http import HttpApp, bearer, http_app
from tests.plugins.identity import accept_rules, insert_user, new_telegram_id
from tests.plugins.queue import run_queued

pytestmark = pytest.mark.integration

API = "/api/v1"
NO_SHOW = "Договорились на 19:00. В 19:40 мастера нет, на сообщения не отвечает."


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


class World:
    def __init__(self, app: HttpApp, worker: AsyncContainer, settings: Settings) -> None:
        self.app, self.worker, self.settings = app, worker, settings
        self.users: list[UserId] = []

    async def execute(self, sql: str, **params: object) -> None:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.begin() as conn:
            await conn.execute(text(sql), params)

    async def row(self, sql: str, **params: object) -> Any:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).first()

    async def user(self, *, telegram_id: int | None = None, role: str | None = None) -> UserId:
        async with self.app.container() as request:
            session = await request.get(AsyncSession)
            user_id = await insert_user(session, telegram_id=telegram_id)
            if role is not None:
                await session.execute(
                    text("INSERT INTO identity.user_roles (user_id, role) VALUES (:id, :role)"),
                    {"id": user_id, "role": role},
                )
            await accept_rules(session, user_id)
        self.users.append(user_id)
        return user_id

    async def deal(self, client: UserId, performer: UserId) -> str:
        """Заявка, отклик исполнителя, прошедший проверку, и выбор клиента: сделка `agreed`."""
        job_id = new_id()
        now = datetime.now(UTC)
        await self.execute(
            "INSERT INTO jobs.jobs (id, client_id, status, title, description, content_lang,"
            " category_id, category_path, urgency, budget_type, city_id, published_at,"
            " expires_at, version) SELECT :id, :client, 'published', 'Повесить люстру', '', 'ru',"
            " c.id, ARRAY[c.id], 'this_week', 'negotiable', ci.id, :published, :expires, 1"
            " FROM geo.cities ci, (SELECT min(id) AS id FROM catalog.categories"
            " WHERE parent_id IS NOT NULL AND is_active AND jobs_enabled AND risk_level = 0) c"
            " WHERE ci.slug = 'novi-sad'",
            id=job_id,
            client=client,
            published=now - timedelta(minutes=30),
            expires=now + timedelta(days=7),
        )
        headers = bearer(self.settings, performer) | {"Idempotency-Key": new_id().hex}
        reply = await self.app.client.post(
            f"{API}/jobs/{job_id}/responses",
            json={"message": f"Могу сегодня. {new_id().hex[-8:]}", "price_type": "negotiable"},
            headers=headers,
        )
        assert reply.status_code == 201, reply.text
        response_id = reply.json()["id"]
        await self.execute(
            "UPDATE jobs.responses SET review = 'clear' WHERE id = :id", id=UUID(response_id)
        )
        accepted = await self.post(client, f"/responses/{response_id}/accept")
        assert accepted.status_code == 200, accepted.text
        deal_id: str = accepted.json()["deal_id"]
        return deal_id

    async def photo(self, owner: UserId, purpose: str = "dispute") -> str:
        """Готовый файл: варианты — в приватном бакете (назначение `dispute`)."""
        media_id = new_id()
        variants = {"md": {"key": f"m/{media_id}/md.webp", "w": 800, "h": 600}}
        await self.execute(
            "INSERT INTO media.assets (id, owner_id, kind, purpose, status, bucket, object_key,"
            " mime_type, size_bytes, variants) VALUES (:id, :owner, 'image', :purpose, 'ready',"
            " 'incoming', :key, 'image/jpeg', 1000, CAST(:variants AS jsonb))",
            id=media_id,
            owner=owner,
            purpose=purpose,
            key=f"{purpose}/2026/10/{media_id}/original",
            variants=json.dumps(variants),
        )
        return str(media_id)

    async def post(self, user: UserId, path: str, body: Any = None) -> httpx.Response:
        return await self.app.client.post(
            f"{API}{path}", json=body, headers=bearer(self.settings, user)
        )

    async def get(self, user: UserId, path: str) -> httpx.Response:
        return await self.app.client.get(f"{API}{path}", headers=bearer(self.settings, user))

    async def dispute(
        self,
        opener: UserId,
        deal_id: str,
        *,
        kind: str = "no_show",
        photos: list[str] | None = None,
    ) -> dict[str, Any]:
        reply = await self.post(
            opener,
            f"/deals/{deal_id}/dispute",
            {"kind": kind, "description": NO_SHOW, "media_ids": photos or []},
        )
        assert reply.status_code == 201, reply.text
        body: dict[str, Any] = reply.json()
        return body

    async def run(self, task: str, user_id: UUID, by: str = "opened_by") -> int:
        return await run_queued(self.worker, task, user_id=user_id, by=by)

    async def case(self, dispute_id: str) -> Any:
        return await self.row(
            "SELECT id, queue, status, subject_id, media_ids, evidence, due_at, reason_code"
            " FROM moderation.cases WHERE entity_type = 'dispute' AND entity_id = :id"
            " ORDER BY created_at DESC LIMIT 1",
            id=UUID(dispute_id),
        )

    async def notifications(self, user: UserId) -> list[tuple[str, dict[str, Any]]]:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT type, payload FROM notifications.notifications"
                        " WHERE user_id = :user ORDER BY id"
                    ),
                    {"user": user},
                )
            ).all()
        return [(row.type, row.payload) for row in rows]


@pytest.fixture
async def world(
    web: HttpApp, worker: AsyncContainer, storage_settings: Settings
) -> AsyncIterator[World]:
    created = World(web, worker, storage_settings)
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


async def test_dispute_opens_a_p1_case_and_wakes_the_other_party(world: World) -> None:
    client, performer, stranger = await world.user(), await world.user(), await world.user()
    deal_id = await world.deal(client, performer)
    photo = await world.photo(client)
    foreign_photo = await world.photo(performer)
    job_photo = await world.photo(client, purpose="job")

    outsider = await world.post(
        stranger, f"/deals/{deal_id}/dispute", {"kind": "other", "description": "Чужая сделка"}
    )
    not_mine = await world.post(
        client,
        f"/deals/{deal_id}/dispute",
        {"kind": "no_show", "description": NO_SHOW, "media_ids": [foreign_photo]},
    )
    wrong_purpose = await world.post(
        client,
        f"/deals/{deal_id}/dispute",
        {"kind": "no_show", "description": NO_SHOW, "media_ids": [job_photo]},
    )
    opened = await world.dispute(client, deal_id, photos=[photo])
    again = await world.post(
        performer, f"/deals/{deal_id}/dispute", {"kind": "other", "description": "Встречный"}
    )
    frozen = await world.post(performer, f"/deals/{deal_id}/complete")

    assert (outsider.status_code, outsider.json()["code"]) == (404, "deal_not_found")
    assert (not_mine.status_code, not_mine.json()["code"]) == (404, "media_not_found")
    assert (wrong_purpose.status_code, wrong_purpose.json()["code"]) == (
        409,
        "media_state_conflict",
    )
    assert {key: opened[key] for key in ("status", "kind", "opened_by_me", "deal_status")} == {
        "status": "open",
        "kind": "no_show",
        "opened_by_me": True,
        "deal_status": "disputed",
    }
    respond_by = datetime.fromisoformat(opened["respond_by"])
    created_at = datetime.fromisoformat(opened["created_at"])
    assert respond_by - created_at == timedelta(hours=48)
    [evidence] = opened["photos"]
    assert evidence["id"] == photo
    assert evidence["variants"][0]["url"].startswith("http")  # presigned GET приватного бакета
    assert (again.status_code, again.json()["code"]) == (409, "deal_not_active")
    assert (frozen.status_code, frozen.json()["code"]) == (409, "deal_not_active")

    # кейс P1 о второй стороне: фото — под legal hold, срок — после 48 ч на ответ
    assert await world.run("moderation.open_dispute_case", client) == 1
    case = await world.case(opened["id"])
    assert (case.queue, case.status, case.subject_id) == ("fraud", "pending", performer)
    assert [str(media_id) for media_id in case.media_ids] == [photo]
    assert case.due_at > respond_by
    assert case.evidence[0]["kind"] == "no_show"
    # второй стороне — «сообщил о проблеме» и «Ответить» сразу на S52
    assert await world.run("notifications.notify_dispute_opened", client) == 1
    assert await world.run("analytics.capture_dispute_opened", client) == 1
    [(kind, payload)] = [n for n in await world.notifications(performer) if n[0].startswith("dis")]
    assert kind == "dispute.opened"
    assert payload["link"] == encode_start_param(StartLink(type=LinkType.DISPUTE, id=UUID(deal_id)))
    assert {key: payload["params"][key] for key in ("by", "kind")} == {
        "by": "client",
        "kind": "no_show",
    }
    # карточка сделки: спор и фото — сторонам; чужому — 404
    card = (await world.get(performer, f"/deals/{deal_id}/card")).json()
    assert (card["status"], card["dispute"]["opened_by_me"]) == ("disputed", False)
    assert [item["id"] for item in card["dispute"]["photos"]] == [photo]
    assert (await world.get(stranger, f"/deals/{deal_id}/card")).status_code == 404


async def test_answer_and_withdrawal_change_the_dispute(world: World) -> None:
    client, performer = await world.user(), await world.user()
    deal_id = await world.deal(client, performer)
    opened = await world.dispute(performer, deal_id, kind="other")
    answer_photo = await world.photo(client)

    by_opener = await world.post(performer, f"/deals/{deal_id}/dispute/respond", {"text": "Я"})
    answered = await world.post(
        client,
        f"/deals/{deal_id}/dispute/respond",
        {"text": "Мастер пришёл в 20:10, работу сделал", "media_ids": [answer_photo]},
    )
    twice = await world.post(client, f"/deals/{deal_id}/dispute/respond", {"text": "Ещё"})

    assert (by_opener.status_code, by_opener.json()["reason"]) == (
        409,
        "not_respondent",
    )
    body = answered.json()
    assert (answered.status_code, body["status"], body["response"]) == (
        200,
        "answered",
        "Мастер пришёл в 20:10, работу сделал",
    )
    assert [item["id"] for item in body["response_photos"]] == [answer_photo]
    assert (twice.status_code, twice.json()["code"]) == (409, "dispute_state_conflict")
    # кейс: открыт — и ответ с фото второй стороны (задачи могут прийти в любом порядке)
    assert await world.run("moderation.note_dispute_answer", performer) == 1
    assert await world.run("moderation.open_dispute_case", performer) == 1
    case = await world.case(opened["id"])
    assert [entry["event"] for entry in case.evidence] == ["opened", "answered"]
    assert {str(media_id) for media_id in case.media_ids} == {answer_photo}

    not_opener = await world.post(client, f"/deals/{deal_id}/dispute/withdraw")
    withdrawn = await world.post(performer, f"/deals/{deal_id}/dispute/withdraw")

    assert (not_opener.status_code, not_opener.json()["reason"]) == (409, "not_opener")
    assert (withdrawn.json()["status"], withdrawn.json()["deal_status"]) == ("withdrawn", "agreed")
    assert await world.run("moderation.close_dispute_case", performer) == 1
    closed = await world.case(opened["id"])
    assert (closed.status, closed.reason_code) == ("approved", "dispute_withdrawn")
    # сделка снова идёт, и спор можно открыть снова
    marked = await world.post(client, f"/deals/{deal_id}/complete")
    assert (marked.status_code, marked.json()["status"]) == (200, "agreed")
    reopened = await world.dispute(client, deal_id)
    assert reopened["id"] != opened["id"]


async def test_no_answer_in_48_hours_marks_the_case(world: World) -> None:
    client, performer = await world.user(), await world.user()
    deal_id = await world.deal(client, performer)
    opened = await world.dispute(client, deal_id)
    assert await world.run("moderation.open_dispute_case", client) == 1
    await world.execute(
        "UPDATE deals.disputes SET respond_by = now() - interval '1 minute' WHERE id = :id",
        id=UUID(opened["id"]),
    )

    async with world.worker() as request:
        sweep = await request.get(SweepDisputes)
        marked = await sweep(SweepDisputesCommand())
        again = await sweep(SweepDisputesCommand())

    assert marked >= 1
    assert again == 0
    card = (await world.get(client, f"/deals/{deal_id}/card")).json()
    assert card["dispute"]["status"] == "no_response"
    assert await world.run("moderation.note_dispute_unanswered", client) == 1
    case = await world.case(opened["id"])
    assert [entry["event"] for entry in case.evidence] == ["opened", "no_response"]
    assert case.status == "pending"
    # поздний ответ модератору тоже пригодится
    late = await world.post(performer, f"/deals/{deal_id}/dispute/respond", {"text": "Болел"})
    assert late.json()["status"] == "answered"


async def test_moderator_resolves_and_both_parties_hear_why(world: World) -> None:
    client, performer = await world.user(), await world.user()
    moderator_tg, outsider_tg = new_telegram_id(), new_telegram_id()
    moderator = await world.user(telegram_id=moderator_tg, role="moderator")
    await world.user(telegram_id=outsider_tg)
    deal_id = await world.deal(client, performer)
    photo = await world.photo(client)
    opened = await world.dispute(client, deal_id, photos=[photo])
    assert await world.run("moderation.open_dispute_case", client) == 1
    case_id = str((await world.case(opened["id"])).id)

    refused = await dispute_show(world.worker, case_ref=case_id, by_telegram_id=outsider_tg)
    shown = await dispute_show(world.worker, case_ref=case_id, by_telegram_id=moderator_tg)
    plain = await moderation_decide(
        world.worker,
        case_ref=case_id,
        approve=True,
        by_telegram_id=moderator_tg,
        reason=None,
        severity=None,
        note=None,
    )

    assert refused.lines == ("dispute-show: not a moderator (see staff-grant)",)
    assert shown.ok
    assert any(NO_SHOW in line for line in shown.lines)
    assert any(line.strip().startswith(f"{photo}  http") for line in shown.lines)
    viewed = await world.row(
        "SELECT actor_kind, changes FROM platform.audit_log"
        " WHERE action = 'moderation.dispute.evidence_viewed' AND actor_id = :moderator",
        moderator=moderator,
    )
    assert viewed.actor_kind == "staff"
    assert viewed.changes["media_ids"] == [photo]
    assert (plain.ok, "case_kind_conflict" in plain.lines[0]) == (False, True)

    resolved = await dispute_resolve(
        world.worker,
        case_ref=case_id,
        outcome="cancelled",
        by_telegram_id=moderator_tg,
        reason="no_show",
        severity="minor",
        note="мастер не пришёл, на сообщения не отвечал",
    )
    twice = await dispute_resolve(
        world.worker,
        case_ref=case_id,
        outcome="completed",
        by_telegram_id=moderator_tg,
        reason="work_done",
        severity=None,
        note=None,
    )

    assert resolved.lines == (
        f"case {case_id}: rejected, sanction warning; deal {deal_id}: cancelled",
    )
    assert not twice.ok
    deal = await world.row(
        "SELECT status, cancel_reason, cancelled_by FROM deals.deals WHERE id = :id",
        id=UUID(deal_id),
    )
    assert tuple(deal) == ("cancelled", "dispute", None)
    card = (await world.get(client, f"/deals/{deal_id}/card")).json()
    assert {key: card["dispute"][key] for key in ("status", "outcome", "reason_code")} == {
        "status": "resolved",
        "outcome": "cancelled",
        "reason_code": "no_show",
    }
    # обеим сторонам — решение и причина; «сделка отменена» отдельно не приходит
    assert await world.run("notifications.notify_dispute_resolved", client, by="client_id") == 1
    assert await world.run("notifications.notify_deal_cancelled", client, by="client_id") == 1
    for party in (client, performer):
        kinds = [kind for kind, _ in await world.notifications(party)]
        assert "dispute.resolved" in kinds
        assert "deal.cancelled" not in kinds
    [(_, payload)] = [n for n in await world.notifications(client) if n[0] == "dispute.resolved"]
    assert payload["params"] == {
        "title": "Повесить люстру",
        "outcome": "cancelled",
        "reason": "no_show",
    }


async def test_open_dispute_holds_account_deletion_and_evidence(world: World) -> None:
    client, performer = await world.user(), await world.user()
    deal_id = await world.deal(client, performer)
    photo = await world.photo(client)
    opened = await world.dispute(client, deal_id, photos=[photo])
    requested = await world.post(performer, "/me/deletion")
    assert requested.status_code == 200, requested.text
    await world.execute(
        "UPDATE identity.deletion_requests SET execute_after = now() - interval '1 minute'"
        " WHERE user_id = :id",
        id=performer,
    )

    async with world.app.container() as request:
        report = await (await request.get(ProcessDeletions))(ProcessDeletionsCommand())
        held = await (await request.get(LegalHold)).held([MediaId(UUID(photo))])

    assert report.held >= 1
    status = await world.row("SELECT status FROM identity.users WHERE id = :id", id=performer)
    assert status.status != "deleted"
    assert held == {UUID(photo)}

    withdrawn = await world.post(client, f"/deals/{deal_id}/dispute/withdraw")
    assert withdrawn.status_code == 200
    assert await world.run("moderation.open_dispute_case", client) == 1  # уже отозван — без кейса
    assert await world.case(opened["id"]) is None
    async with world.app.container() as request:
        await (await request.get(ProcessDeletions))(ProcessDeletionsCommand())
        released = await (await request.get(LegalHold)).held([MediaId(UUID(photo))])

    status = await world.row("SELECT status FROM identity.users WHERE id = :id", id=performer)
    assert status.status == "deleted"
    assert released == set()
