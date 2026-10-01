"""Профиль исполнителя проходит модерацию (DEVELOPMENT_PLAN 2.8a): отправка → автопроверка →
P2 (новый профиль всегда проверяет человек) → одобрение → опубликован и уведомление; отказ →
снова черновик с причиной. Контейнер процесса, данные коммитятся.
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._wiring import make_worker_container
from app.modules.moderation.application.use_cases.auto_check import AutoCheck, AutoCheckCommand
from app.modules.moderation.application.use_cases.decide_case import (
    DecideCase,
    DecideCaseCommand,
)
from app.modules.moderation.domain.cases import EntityType
from app.modules.moderation.domain.pipeline import Route
from app.modules.pricing.application.use_cases.add_service import AddService, AddServiceCommand
from app.modules.pricing.domain.service import PriceType
from app.modules.specialists.application.use_cases.create_profile import (
    CreateProfile,
    CreateProfileCommand,
)
from app.modules.specialists.application.use_cases.edit_profile import (
    EditProfile,
    EditProfileCommand,
)
from app.modules.specialists.application.use_cases.set_profile_areas import (
    SetProfileAreas,
    SetProfileAreasCommand,
)
from app.modules.specialists.application.use_cases.set_profile_categories import (
    SetProfileCategories,
    SetProfileCategoriesCommand,
)
from app.modules.specialists.application.use_cases.submit_profile import (
    SubmitProfile,
    SubmitProfileCommand,
)
from app.modules.specialists.domain.profile import ProfileKind
from app.platform.contracts.events.moderation import ModerationDecision
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, UserId
from app.platform.settings import Settings
from tests.plugins.identity import accept_rules, insert_user

pytestmark = pytest.mark.integration


@pytest.fixture
async def container(
    settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[AsyncContainer]:
    container = make_worker_container(settings)
    try:
        yield container
    finally:
        await container.close()


async def scalar(container: AsyncContainer, sql: str, **params: object) -> object:
    engine = await container.get(AsyncEngine)
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).scalar()


async def submitted_profile(container: AsyncContainer) -> tuple[UserId, UUID]:
    city = CityId(
        int(str(await scalar(container, "SELECT id FROM geo.cities WHERE slug = 'novi-sad'")))
    )
    district = DistrictId(
        int(
            str(
                await scalar(
                    container, "SELECT min(id) FROM geo.districts WHERE city_id = :c", c=city
                )
            )
        )
    )
    category = CategoryId(
        int(
            str(
                await scalar(
                    container,
                    "SELECT min(id) FROM catalog.categories WHERE is_active AND risk_level = 0"
                    " AND parent_id IS NOT NULL",
                )
            )
        )
    )
    async with container() as request:
        session = await request.get(AsyncSession)
        user_id = await insert_user(session)
        await accept_rules(session, user_id)
    steps: list[tuple[type[Any], Any]] = [
        (CreateProfile, CreateProfileCommand(actor_id=user_id, kind=ProfileKind.PRO, city_id=city)),
        (
            EditProfile,
            EditProfileCommand(
                actor_id=user_id, headline="Электрик, 10 лет", work_modes=["at_client"]
            ),
        ),
        (
            SetProfileCategories,
            SetProfileCategoriesCommand(actor_id=user_id, category_ids=[category]),
        ),
        (SetProfileAreas, SetProfileAreasCommand(actor_id=user_id, district_ids=[district])),
        (
            AddService,
            AddServiceCommand(
                actor_id=user_id,
                title="Вызов мастера",
                price_type=PriceType.FROM,
                price_min=100_000,
            ),
        ),
        (SubmitProfile, SubmitProfileCommand(actor_id=user_id)),
    ]
    profile_id = None
    for use_case, command in steps:
        async with container() as request:
            result = await (await request.get(use_case))(command)
            if use_case is not AddService:
                profile_id = result.id
    assert profile_id is not None
    return user_id, profile_id


async def auto_check(container: AsyncContainer, user_id: UserId, profile_id: UUID) -> Route:
    async with container() as request:
        routing = await (await request.get(AutoCheck))(
            AutoCheckCommand(
                entity_type=EntityType.PROFILE, entity_id=profile_id, author_id=user_id
            )
        )
    assert routing is not None
    return routing.route


async def decide(container: AsyncContainer, profile_id: UUID, command: dict[str, object]) -> None:
    case_id = await scalar(
        container,
        "SELECT id FROM moderation.cases WHERE entity_id = :id AND status = 'pending'",
        id=profile_id,
    )
    async with container() as request:
        await (await request.get(DecideCase))(DecideCaseCommand(case_id=case_id, **command))  # type: ignore[arg-type]


async def jobs(container: AsyncContainer, task: str, user_id: UserId) -> int:
    count = await scalar(
        container,
        "SELECT count(*) FROM procrastinate_jobs WHERE task_name = :task AND status = 'todo'"
        " AND (args->'payload'->>'user_id' = :id OR args->'payload'->>'author_id' = :id)",
        task=task,
        id=str(user_id),
    )
    return int(str(count))


async def drop_jobs(container: AsyncContainer, user_id: UserId) -> None:
    engine = await container.get(AsyncEngine)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM procrastinate_jobs WHERE status = 'todo' AND ("
                "args->'payload'->>'user_id' = :id OR args->'payload'->>'author_id' = :id)"
            ),
            {"id": str(user_id)},
        )


async def test_approved_profile_is_published_and_the_author_told(container: AsyncContainer) -> None:
    user_id, profile_id = await submitted_profile(container)
    try:
        assert await auto_check(container, user_id, profile_id) is Route.REVIEW  # всегда человек
        assert (
            await scalar(
                container, "SELECT queue FROM moderation.cases WHERE entity_id = :id", id=profile_id
            )
            == "premod"
        )

        await decide(container, profile_id, {"verdict": ModerationDecision.APPROVED})

        status = await scalar(
            container, "SELECT status FROM specialists.profiles WHERE id = :id", id=profile_id
        )
        assert status == "published"
        assert await jobs(container, "notifications.notify_profile_published", user_id) == 1
    finally:
        await drop_jobs(container, user_id)


async def test_rejected_profile_goes_back_for_fixes(container: AsyncContainer) -> None:
    user_id, profile_id = await submitted_profile(container)
    try:
        await auto_check(container, user_id, profile_id)

        await decide(
            container,
            profile_id,
            {"verdict": ModerationDecision.REJECTED, "reason_code": "contact_leak"},
        )

        status, reason = (
            await scalar(
                container,
                "SELECT status FROM specialists.profiles WHERE id = :id",
                id=profile_id,
            ),
            await scalar(
                container,
                "SELECT rejection_reason FROM specialists.profiles WHERE id = :id",
                id=profile_id,
            ),
        )
        assert (status, reason) == ("draft", "contact_leak")
        assert await jobs(container, "notifications.notify_moderation_decision", user_id) == 1
    finally:
        await drop_jobs(container, user_id)
