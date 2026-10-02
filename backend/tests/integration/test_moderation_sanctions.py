"""Модерация через настоящие фасады (DEVELOPMENT_PLAN 2.5a): решение по кейсу ставит санкцию
через identity, опускает уровень доверия и ставит задачи уведомлений и отзыва сессий; очистка
медиа не стирает доказательства открытого кейса. Контейнер процесса, данные коммитятся —
у теста свой пользователь, его задачи в конце снимаются с очереди.
"""

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._wiring import make_worker_container
from app.modules.media.application.use_cases.purge_deleted import (
    PurgeDeleted,
    PurgeDeletedCommand,
)
from app.modules.moderation.application.use_cases.decide_case import (
    DecideCase,
    DecideCaseCommand,
)
from app.modules.moderation.application.use_cases.open_case import OpenCase, OpenCaseCommand
from app.modules.moderation.domain.cases import CaseTrigger, EntityType
from app.modules.moderation.domain.queues import Queue
from app.modules.moderation.domain.sanctions import SanctionStep, Severity
from app.platform.contracts.events.moderation import ModerationDecision
from app.platform.kernel.ids import CaseId, MediaId, UserId, new_id
from app.platform.settings import Settings
from tests.plugins.identity import insert_user

pytestmark = pytest.mark.integration


@pytest.fixture
async def container(settings: Settings) -> AsyncIterator[AsyncContainer]:
    container = make_worker_container(settings)
    try:
        yield container
    finally:
        await container.close()


async def new_user(container: AsyncContainer) -> UserId:
    async with container() as request:
        return await insert_user(await request.get(AsyncSession))


async def open_case(
    container: AsyncContainer, user_id: UserId, media: tuple[MediaId, ...] = ()
) -> CaseId:
    async with container() as request:
        open_ = await request.get(OpenCase)
        return await open_(
            OpenCaseCommand(
                queue=Queue.PREMOD,
                entity_type=EntityType.JOB,
                entity_id=new_id(),
                subject_id=user_id,
                trigger=CaseTrigger.AUTO_FLAG,
                media_ids=media,
            )
        )


async def decide(container: AsyncContainer, command: DecideCaseCommand) -> SanctionStep | None:
    async with container() as request:
        decide_ = await request.get(DecideCase)
        return (await decide_(command)).sanction


async def rows(container: AsyncContainer, sql: str, **params: object) -> list[tuple[Any, ...]]:
    engine = await container.get(AsyncEngine)
    async with engine.connect() as conn:
        return [tuple(row) for row in (await conn.execute(text(sql), params)).all()]


async def drop_jobs(container: AsyncContainer, *keys: UUID) -> None:
    engine = await container.get(AsyncEngine)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM procrastinate_jobs WHERE status = 'todo' AND ("
                " args->'payload'->>'user_id' = ANY(:keys)"
                " OR args->'payload'->>'author_id' = ANY(:keys)"
                " OR args->'payload'->>'media_id' = ANY(:keys))"
            ),
            {"keys": [str(key) for key in keys]},
        )


def minor(case_id: CaseId) -> DecideCaseCommand:
    return DecideCaseCommand(
        case_id=case_id,
        verdict=ModerationDecision.REJECTED,
        reason_code="contact_leak",
        severity=Severity.MINOR,
    )


async def test_strike_restricts_through_identity_and_lowers_trust(
    container: AsyncContainer,
) -> None:
    user_id = await new_user(container)
    try:
        warned, struck = await open_case(container, user_id), await open_case(container, user_id)

        assert await decide(container, minor(warned)) is SanctionStep.WARNING
        assert await decide(container, minor(struck)) is SanctionStep.STRIKE_1

        restrictions = await rows(
            container,
            "SELECT kind, reason_code, case_id, round(extract(epoch FROM ends_at - starts_at))"
            " FROM identity.restrictions WHERE user_id = :id",
            id=user_id,
        )
        week = timedelta(days=7).total_seconds()  # срок — от решения, с точностью до секунды
        assert restrictions == [("limited", "contact_leak", struck, week)]
        [(level, penalized)] = await rows(
            container,
            "SELECT trust_level, trust_penalty_at IS NOT NULL FROM identity.users WHERE id = :id",
            id=user_id,
        )
        assert (level, penalized) == (0, True)
        jobs = await rows(
            container,
            "SELECT task_name, count(*) FROM procrastinate_jobs WHERE status = 'todo' AND"
            " (args->'payload'->>'user_id' = :id OR args->'payload'->>'author_id' = :id)"
            " GROUP BY task_name ORDER BY task_name",
            id=str(user_id),
        )
        assert jobs == [
            ("identity.revoke_restricted_sessions", 1),  # limited сессии не трогает
            ("notifications.notify_account_restricted", 1),
            ("notifications.notify_moderation_decision", 2),
            ("search.on_user_restricted", 1),  # профиль пересоберётся: скрыт ли автор
        ]
        decided = await rows(
            container,
            "SELECT changes->>'policy_version', changes->>'sanction' FROM platform.audit_log"
            " WHERE action = 'moderation.case.decided' AND entity_id = ANY(:ids) ORDER BY id",
            ids=[warned, struck],
        )
        assert decided == [("draft-1", "warning"), ("draft-1", "strike_1")]
    finally:
        await drop_jobs(container, user_id)


async def test_purge_keeps_evidence_of_open_cases(container: AsyncContainer) -> None:
    user_id = await new_user(container)
    evidence, free = MediaId(new_id()), MediaId(new_id())
    engine = await container.get(AsyncEngine)
    async with engine.begin() as conn:
        for media_id in (evidence, free):
            await conn.execute(
                text(
                    "INSERT INTO media.assets (id, owner_id, kind, purpose, status, bucket,"
                    " object_key, mime_type, size_bytes, deleted_at) VALUES (:id, :owner,"
                    " 'image', 'job', 'deleted', 'incoming', :key, 'image/jpeg', 1024,"
                    " now() - interval '31 days')"
                ),
                {"id": media_id, "owner": user_id, "key": f"job/2026/08/{media_id}/original"},
            )
    try:
        case_id = await open_case(container, user_id, media=(evidence,))

        async with container() as request:
            await (await request.get(PurgeDeleted))(PurgeDeletedCommand())
        state = await rows(
            container,
            "SELECT id, purged_at IS NOT NULL, held_until > now() FROM media.assets"
            " WHERE id = ANY(:ids)",
            ids=[evidence, free],
        )
        assert sorted(state, key=lambda row: row[0] != evidence) == [
            (evidence, False, True),  # доказательство открытого кейса удержано
            (free, True, None),
        ]

        await decide(
            container, DecideCaseCommand(case_id=case_id, verdict=ModerationDecision.APPROVED)
        )
        async with engine.begin() as conn:  # сутки прошли: очистка проверяет снова
            await conn.execute(
                text(
                    "UPDATE media.assets SET held_until = now() - interval '1 minute'"
                    " WHERE id = :id"
                ),
                {"id": evidence},
            )
        async with container() as request:
            await (await request.get(PurgeDeleted))(PurgeDeletedCommand())
        assert await rows(
            container, "SELECT purged_at IS NOT NULL FROM media.assets WHERE id = :id", id=evidence
        ) == [(True,)]
    finally:
        await drop_jobs(container, user_id, evidence, free)
