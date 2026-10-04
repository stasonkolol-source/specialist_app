"""Апелляции через API (DEVELOPMENT_PLAN 2.5b): `POST /appeals` с экрана S49b — кейс в очереди
Appeals об обжалованном решении; повтор — та же апелляция; нечего обжаловать — 404.
Удовлетворённая апелляция снимает санкцию и отменяет ступень лестницы, итог уходит автору
уведомлением. Контейнер процесса, данные коммитятся — у теста свои пользователи.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from tests.plugins.http import HttpApp, bearer, http_app
from tests.plugins.identity import insert_user

from app.entrypoints._wiring import module_routers
from app.modules.moderation.application.use_cases.decide_case import (
    DecideCase,
    DecideCaseCommand,
)
from app.modules.moderation.application.use_cases.open_case import OpenCase, OpenCaseCommand
from app.modules.moderation.domain.cases import CaseTrigger, EntityType
from app.modules.moderation.domain.queues import Queue
from app.modules.moderation.domain.sanctions import Severity
from app.platform.contracts.events.moderation import ModerationDecision
from app.platform.kernel.ids import CaseId, UserId, new_id
from app.platform.settings import Settings

pytestmark = pytest.mark.integration

API = "/api/v1"


@dataclass
class Web:
    app: HttpApp
    settings: Settings

    @property
    def container(self) -> AsyncContainer:
        return self.app.container


@pytest.fixture
async def web(settings: Settings) -> AsyncIterator[Web]:
    async with http_app(settings, *module_routers()) as app:
        yield Web(app, settings)


async def user(web: Web) -> UserId:
    async with web.container() as request:
        return await insert_user(await request.get(AsyncSession))


async def suspended(web: Web, subject: UserId, moderator: UserId) -> CaseId:
    """Решение с санкцией: серьёзное нарушение — приостановка аккаунта."""
    async with web.container() as request:
        case_id = await (await request.get(OpenCase))(
            OpenCaseCommand(
                queue=Queue.FRAUD,
                entity_type=EntityType.JOB,
                entity_id=new_id(),
                subject_id=subject,
                trigger=CaseTrigger.REPORT,
                details={"signals": ["report:fraud"]},
            )
        )
    await decide(
        web, case_id, moderator, ModerationDecision.REJECTED, "prepayment_scam", Severity.SERIOUS
    )
    return case_id


async def decide(
    web: Web,
    case_id: CaseId,
    moderator: UserId,
    verdict: ModerationDecision,
    reason: str | None = None,
    severity: Severity | None = None,
) -> None:
    async with web.container() as request:
        await (await request.get(DecideCase))(
            DecideCaseCommand(
                case_id=case_id,
                verdict=verdict,
                reason_code=reason,
                severity=severity,
                moderator_id=moderator,
            )
        )


async def row(web: Web, sql: str, **params: object) -> Any:
    engine = await web.container.get(AsyncEngine)
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).first()


async def appeal(web: Web, author: UserId, body: dict[str, object]) -> Any:
    return await web.app.client.post(
        f"{API}/appeals", json=body, headers=bearer(web.settings, author)
    )


async def test_appeal_opens_an_appeals_case_once(web: Web) -> None:
    author, moderator = await user(web), await user(web)
    decision = await suspended(web, author, moderator)

    first = await appeal(web, author, {"restriction": "suspended"})
    again = await appeal(web, author, {"case_id": str(decision)})
    other = await appeal(web, author, {"restriction": "posting_blocked"})
    foreign = await appeal(web, moderator, {"case_id": str(decision)})

    assert first.status_code == 201, first.text
    body = first.json()
    assert (body["appeal_of"], body["status"]) == (str(decision), "pending")
    assert body["repeated"] is False
    assert (again.status_code, again.json()["id"]) == (200, body["id"])  # «уже обжаловано»
    assert again.json()["repeated"] is True
    assert (other.status_code, other.json()["code"]) == (404, "appeal_target_not_found")
    assert (foreign.status_code, foreign.json()["code"]) == (404, "appeal_target_not_found")
    case = await row(
        web,
        "SELECT queue, trigger, subject_id, appeal_of, status FROM moderation.cases WHERE id = :id",
        id=body["id"],
    )
    assert tuple(case) == ("appeals", "appeal", author, decision, "pending")


async def test_granted_appeal_lifts_the_sanction(web: Web) -> None:
    author, moderator = await user(web), await user(web)
    decision = await suspended(web, author, moderator)
    filed = await appeal(web, author, {})  # без вида санкции — последняя
    assert filed.status_code == 201, filed.text

    await decide(web, CaseId(filed.json()["id"]), moderator, ModerationDecision.APPROVED)

    sanction = await row(
        web, "SELECT revoked_at FROM moderation.sanctions WHERE case_id = :id", id=decision
    )
    restriction = await row(
        web, "SELECT lifted_at FROM identity.restrictions WHERE case_id = :id", id=decision
    )
    assert sanction.revoked_at is not None
    assert restriction.lifted_at is not None
    notice = await row(
        web,
        "SELECT count(*) AS n FROM procrastinate_jobs WHERE task_name ="
        " 'notifications.notify_appeal_decided' AND args->'payload'->>'user_id' = :user",
        user=str(author),
    )
    assert notice.n == 1


async def test_denied_appeal_keeps_the_decision(web: Web) -> None:
    author, moderator = await user(web), await user(web)
    decision = await suspended(web, author, moderator)
    filed = await appeal(web, author, {"restriction": "suspended"})

    await decide(
        web,
        CaseId(filed.json()["id"]),
        moderator,
        ModerationDecision.REJECTED,
        "decision_upheld",
    )

    restriction = await row(
        web, "SELECT lifted_at FROM identity.restrictions WHERE case_id = :id", id=decision
    )
    assert restriction.lifted_at is None
    repeat = await appeal(web, author, {"restriction": "suspended"})
    assert (repeat.status_code, repeat.json()["status"]) == (200, "rejected")
