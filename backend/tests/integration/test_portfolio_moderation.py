"""Модерация работ портфолио (DEVELOPMENT_PLAN 6.7, ARCHITECTURE §14.1, ADR-0016).

Новая работа — `pending`: её видит только владелец (S37), карточка S08/S10 — нет. Подпись
проверяется, когда фото прошло проверку (итог фото — как у `moderation.check_image`: запись
итога и повторный запрос проверки работ в одной транзакции); чистые подпись и фото публикуют
работу, флаг — кейс P2 о работе, решение модератора публикует или скрывает. Портфолио нового
профиля всегда проверяет человек. Задачи — как в воркере; данные коммитятся.
"""

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.entrypoints._wiring import make_worker_container
from app.modules.media.api import MediaModeration, ModerationVerdict
from app.modules.moderation.application.use_cases.decide_case import (
    DecideCase,
    DecideCaseCommand,
)
from app.modules.specialists.api import SpecialistsApi
from app.modules.specialists.application.portfolio_views import PortfolioViews
from app.modules.specialists.application.use_cases.add_portfolio_work import (
    AddPortfolioWork,
    AddPortfolioWorkCommand,
)
from app.platform.contracts.events.moderation import ModerationDecision
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import CaseId, MediaId, new_id
from app.platform.settings import Settings
from tests.plugins.queue import run_queued
from tests.plugins.search import Specialist

pytestmark = pytest.mark.integration

PHONE = "Люстра, звоните +381 64 123 4567"


@pytest.fixture
async def worker(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[AsyncContainer]:
    container = make_worker_container(storage_settings)
    try:
        yield container
    finally:
        await container.close()


class Owner:
    def __init__(self, container: AsyncContainer) -> None:
        self.container = container
        self.specialist = Specialist(container)

    async def ready(self) -> None:
        """Опубликованный профиль; его собственная проверка из очереди убрана — считаем только
        проверки работ."""
        await self.specialist.publish()
        await self.specialist.execute(
            "DELETE FROM procrastinate_jobs WHERE task_name = 'moderation.auto_check'"
            " AND args->'payload'->>'entity_id' = :id",
            id=str(self.specialist.profile_id),
        )

    async def work(self, caption: str | None = None) -> tuple[UUID, MediaId]:
        """Готовое фото портфолио (ещё не проверенное) — работой в портфолио."""
        media_id = MediaId(new_id())
        await self.specialist.execute(
            "INSERT INTO media.assets (id, owner_id, kind, purpose, status, bucket, object_key,"
            " mime_type, size_bytes, variants) VALUES (:id, :owner, 'image', 'portfolio',"
            " 'ready', 'media', :key, 'image/jpeg', 1000, CAST(:variants AS jsonb))",
            id=media_id,
            owner=self.specialist.user_id,
            key=f"portfolio/2026/10/{media_id}/original",
            variants=json.dumps({"thumb": {"key": f"m/{media_id}/thumb.webp", "w": 320, "h": 240}}),
        )
        item = await self.specialist.call(
            AddPortfolioWork,
            AddPortfolioWorkCommand(
                actor_id=self.specialist.user_id, media_id=media_id, caption=caption
            ),
        )
        return item.id, media_id

    async def photo_checked(self, media_id: MediaId, verdict: ModerationVerdict) -> int:
        """Итог проверки фото, как пишет его `moderation.check_image`, и повторный запрос
        проверки ждущих работ (у чистого фото)."""
        async with self.container() as request:
            uow = await request.get(UnitOfWork)
            media = await request.get(MediaModeration)
            specialists: SpecialistsApi = await request.get(SpecialistsApi)
            async with uow:
                assert await media.moderate(media_id, verdict, auto=True)
                if verdict is not ModerationVerdict.APPROVED:
                    return 0
                return await specialists.recheck_works(media_id)

    async def auto_check(self) -> int:
        return await run_queued(
            self.container, "moderation.auto_check", user_id=self.specialist.user_id, by="author_id"
        )

    async def statuses(self) -> dict[UUID, str]:
        """Как видит портфолио владелец (S37)."""
        async with self.container() as request:
            views = await request.get(PortfolioViews)
            works = await views.of_user(self.specialist.user_id)
        assert works is not None
        return {work.id: work.status.value for work in works}

    async def public(self) -> list[UUID]:
        """Как видят работы клиенты (S08, S10)."""
        async with self.container() as request:
            specialists = await request.get(SpecialistsApi)
            profile = await specialists.public_profile(self.specialist.profile_id)
        assert profile is not None
        return [work.id for work in profile.works]

    async def cases(self, work_id: UUID) -> list[dict[str, Any]]:
        engine = await self.container.get(AsyncEngine)
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, queue, status, trigger, evidence, media_ids FROM moderation.cases"
                    " WHERE entity_type = 'portfolio' AND entity_id = :id"
                ),
                {"id": work_id},
            )
            return [dict(row._mapping) for row in rows]

    async def decide(self, case_id: UUID, verdict: ModerationDecision) -> None:
        async with self.container() as request:
            decide = await request.get(DecideCase)
            await decide(
                DecideCaseCommand(
                    case_id=CaseId(case_id),
                    verdict=verdict,
                    reason_code="contact_leak" if verdict is ModerationDecision.REJECTED else None,
                )
            )


async def test_clean_caption_and_photo_publish_the_work(worker: AsyncContainer) -> None:
    owner = Owner(worker)
    await owner.ready()
    await owner.specialist.execute(  # уровень 1: без выборочной пост-модерации (10 % уровня 0)
        "UPDATE identity.users SET trust_level = 1 WHERE id = :id", id=owner.specialist.user_id
    )

    work_id, media_id = await owner.work("Люстра в гостиной")

    assert await owner.statuses() == {work_id: "pending"}  # владелец видит «На проверке»
    assert await owner.public() == []  # клиенты — нет
    # фото ещё не проверено: подпись проверять рано, работа ждёт
    assert await owner.auto_check() == 1
    assert await owner.statuses() == {work_id: "pending"}

    assert await owner.photo_checked(media_id, ModerationVerdict.APPROVED) == 1
    assert await owner.auto_check() == 1

    assert await owner.statuses() == {work_id: "published"}
    assert await owner.public() == [work_id]
    assert await owner.cases(work_id) == []


async def test_flagged_photo_keeps_the_work_waiting(worker: AsyncContainer) -> None:
    owner = Owner(worker)
    await owner.ready()
    work_id, media_id = await owner.work()

    assert await owner.photo_checked(media_id, ModerationVerdict.FLAGGED) == 0
    assert await owner.auto_check() == 1  # первая проверка работы: фото ещё ждёт модератора

    assert await owner.statuses() == {work_id: "pending"}
    assert await owner.public() == []


async def test_flagged_caption_opens_p2_case_and_moderator_decides(
    worker: AsyncContainer,
) -> None:
    owner = Owner(worker)
    await owner.ready()
    kept, kept_media = await owner.work(PHONE)
    hidden, hidden_media = await owner.work(PHONE)
    for media_id in (kept_media, hidden_media):
        assert await owner.photo_checked(media_id, ModerationVerdict.APPROVED) == 1
    assert await owner.auto_check() == 4  # по две на работу: при добавлении и после фото

    assert await owner.statuses() == {kept: "pending", hidden: "pending"}
    assert await owner.public() == []
    [case] = await owner.cases(kept)
    assert (case["queue"], case["status"], case["trigger"]) == ("premod", "pending", "new_content")
    assert case["media_ids"] == [kept_media]  # фото работы — доказательство под legal hold
    assert any("contacts" in signal for signal in case["evidence"][0]["signals"])

    await owner.decide(case["id"], ModerationDecision.APPROVED)
    [other] = await owner.cases(hidden)
    await owner.decide(other["id"], ModerationDecision.REJECTED)

    assert await owner.statuses() == {kept: "published", hidden: "rejected"}
    assert await owner.public() == [kept]


async def test_portfolio_of_a_new_profile_goes_to_a_human(worker: AsyncContainer) -> None:
    owner = Owner(worker)
    await owner.ready()
    await owner.specialist.execute(  # профиль ещё ни разу не публиковался
        "UPDATE specialists.profiles SET published_at = NULL WHERE id = :id",
        id=owner.specialist.profile_id,
    )
    work_id, media_id = await owner.work("Люстра в гостиной")

    assert await owner.photo_checked(media_id, ModerationVerdict.APPROVED) == 1
    assert await owner.auto_check() == 2

    [case] = await owner.cases(work_id)
    assert (case["queue"], case["status"]) == ("premod", "pending")
    assert case["evidence"][0]["signals"] == ["always_review"]
    assert await owner.statuses() == {work_id: "pending"}
