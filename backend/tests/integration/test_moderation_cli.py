"""`cli moderation-queue` и `cli moderation-decide` на контейнере процесса (DEVELOPMENT_PLAN 2.6).

Данные коммитятся: у теста свои пользователи и объект; задачи снимаются с очереди в конце.
"""

from collections.abc import AsyncIterator

import pytest
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._moderation_cli import moderation_decide, moderation_queue
from app.entrypoints._wiring import make_worker_container
from app.modules.moderation.application.use_cases.open_case import OpenCase, OpenCaseCommand
from app.modules.moderation.domain.cases import CaseTrigger, EntityType
from app.modules.moderation.domain.queues import Queue
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings
from tests.plugins.identity import insert_user, new_telegram_id

pytestmark = pytest.mark.integration


@pytest.fixture
async def container(settings: Settings) -> AsyncIterator[AsyncContainer]:
    container = make_worker_container(settings)
    try:
        yield container
    finally:
        await container.close()


async def staff(container: AsyncContainer, role: str | None) -> tuple[UserId, int]:
    telegram_id = new_telegram_id()
    async with container() as request:
        session = await request.get(AsyncSession)
        user_id = await insert_user(session, telegram_id=telegram_id)
        if role is not None:
            await session.execute(
                text("INSERT INTO identity.user_roles (user_id, role) VALUES (:id, :role)"),
                {"id": user_id, "role": role},
            )
            await session.commit()
    return user_id, telegram_id


async def test_moderator_lists_and_decides_a_case(container: AsyncContainer) -> None:
    author, _ = await staff(container, None)
    _, moderator = await staff(container, "moderator")
    _, outsider = await staff(container, None)
    job = new_id()
    async with container() as request:
        case_id = await (await request.get(OpenCase))(
            OpenCaseCommand(
                queue=Queue.FRAUD,
                entity_type=EntityType.JOB,
                entity_id=job,
                subject_id=author,
                trigger=CaseTrigger.REPORT,
                details={"signals": ["classifier:prepayment_scam:0.91"]},
            )
        )
    try:
        listed = await moderation_queue(container, limit=500)
        [line] = [line for line in listed.lines if str(case_id) in line]
        assert f"fraud   job/{job}" in line
        assert "classifier:prepayment_scam:0.91" in line

        refused = await moderation_decide(
            container,
            case_ref=str(case_id),
            approve=False,
            by_telegram_id=outsider,
            reason="prepayment_scam",
            severity="serious",
            note=None,
        )
        incomplete = await moderation_decide(
            container,
            case_ref=str(case_id),
            approve=False,
            by_telegram_id=moderator,
            reason=None,
            severity=None,
            note=None,
        )
        decided = await moderation_decide(
            container,
            case_ref=str(case_id),
            approve=False,
            by_telegram_id=moderator,
            reason="prepayment_scam",
            severity="serious",
            note="подтвердили по переписке",
        )

        assert (refused.ok, refused.lines) == (
            False,
            ("moderation-decide: not a moderator (see staff-grant)",),
        )
        assert not incomplete.ok
        assert "invalid_decision" in incomplete.lines[0]
        assert decided == decided.__class__(
            ok=True, lines=(f"case {case_id}: rejected, sanction suspension",)
        )
    finally:
        engine = await container.get(AsyncEngine)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM procrastinate_jobs WHERE status = 'todo' AND ("
                    "args->'payload'->>'user_id' = :id OR args->'payload'->>'author_id' = :id)"
                ),
                {"id": str(author)},
            )
