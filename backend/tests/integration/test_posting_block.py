"""Санкция на публикацию (posting_blocked) замораживает публичный профиль (QA SEC-01): правки
профиля, районов и услуг, «доступен сегодня», фото профиля, портфолио и прайс — 403
`restricted`, как создание и показ профиля. Проверка — до всего остального: объекты команд
могут и не существовать. Контейнер процесса, данные коммитятся.
"""

from collections.abc import AsyncIterator
from datetime import time
from typing import Any

import pytest
from dishka import AsyncContainer

from app.entrypoints._wiring import make_worker_container
from app.modules.identity.api import RestrictionKind
from app.modules.pricing.application.use_cases.add_service import AddService, AddServiceCommand
from app.modules.pricing.application.use_cases.change_service import (
    ChangeService,
    ChangeServiceCommand,
)
from app.modules.pricing.application.use_cases.remove_service import (
    RemoveService,
    RemoveServiceCommand,
)
from app.modules.pricing.application.use_cases.reorder_services import (
    ReorderServices,
    ReorderServicesCommand,
)
from app.modules.pricing.domain.service import PriceType, ServiceId
from app.modules.specialists.application.use_cases.add_portfolio_work import (
    AddPortfolioWork,
    AddPortfolioWorkCommand,
)
from app.modules.specialists.application.use_cases.caption_portfolio_work import (
    CaptionPortfolioWork,
    CaptionPortfolioWorkCommand,
)
from app.modules.specialists.application.use_cases.edit_profile import (
    EditProfile,
    EditProfileCommand,
)
from app.modules.specialists.application.use_cases.remove_portfolio_work import (
    RemovePortfolioWork,
    RemovePortfolioWorkCommand,
)
from app.modules.specialists.application.use_cases.reorder_portfolio import (
    ReorderPortfolio,
    ReorderPortfolioCommand,
)
from app.modules.specialists.application.use_cases.set_availability import (
    SetAvailability,
    SetAvailabilityCommand,
)
from app.modules.specialists.application.use_cases.set_profile_areas import (
    SetProfileAreas,
    SetProfileAreasCommand,
)
from app.modules.specialists.application.use_cases.set_profile_avatar import (
    SetProfileAvatar,
    SetProfileAvatarCommand,
)
from app.modules.specialists.application.use_cases.set_profile_categories import (
    SetProfileCategories,
    SetProfileCategoriesCommand,
)
from app.modules.specialists.domain.portfolio import PortfolioItemId
from app.platform.kernel.errors import RestrictedError
from app.platform.kernel.ids import MediaId, new_id
from app.platform.settings import Settings
from tests.plugins.search import Specialist

pytestmark = pytest.mark.integration


@pytest.fixture
async def worker(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[AsyncContainer]:
    container = make_worker_container(storage_settings)
    try:
        yield container
    finally:
        await container.close()


def mutations(specialist: Specialist) -> list[tuple[type[Any], object]]:
    """Все правки публичного профиля из SEC-01 — с несуществующими работами и позициями."""
    me = specialist.user_id
    work, service = PortfolioItemId(new_id()), ServiceId(new_id())
    return [
        (EditProfile, EditProfileCommand(actor_id=me, headline="Электрик, звоните напрямую")),
        (
            SetProfileCategories,
            SetProfileCategoriesCommand(actor_id=me, category_ids=[specialist.category]),
        ),
        (SetProfileAreas, SetProfileAreasCommand(actor_id=me, district_ids=[specialist.district])),
        (SetAvailability, SetAvailabilityCommand(actor_id=me, until=time(23, 0))),
        (SetProfileAvatar, SetProfileAvatarCommand(actor_id=me, media_id=None)),
        (
            AddPortfolioWork,
            AddPortfolioWorkCommand(actor_id=me, media_id=MediaId(new_id()), caption=None),
        ),
        (CaptionPortfolioWork, CaptionPortfolioWorkCommand(actor_id=me, item_id=work, caption="")),
        (RemovePortfolioWork, RemovePortfolioWorkCommand(actor_id=me, item_id=work)),
        (ReorderPortfolio, ReorderPortfolioCommand(actor_id=me, item_ids=[work])),
        (
            AddService,
            AddServiceCommand(actor_id=me, title="Срочный выезд", price_type=PriceType.NEGOTIABLE),
        ),
        (ChangeService, ChangeServiceCommand(actor_id=me, service_id=service, title="Выезд")),
        (RemoveService, RemoveServiceCommand(actor_id=me, service_id=service)),
        (ReorderServices, ReorderServicesCommand(actor_id=me, service_ids=[service])),
    ]


async def test_posting_block_freezes_the_public_profile(worker: AsyncContainer) -> None:
    specialist = Specialist(worker)
    await specialist.publish()
    try:
        await specialist.restrict(RestrictionKind.POSTING_BLOCKED, None)

        for use_case, command in mutations(specialist):
            with pytest.raises(RestrictedError) as refused:
                await specialist.call(use_case, command)
            assert refused.value.restriction == "posting_blocked", use_case.__name__

        headline = await specialist.scalar(
            "SELECT headline FROM specialists.profiles WHERE id = :id", id=specialist.profile_id
        )
        assert headline == "Электрик, 10 лет"  # ничего не изменилось
    finally:
        await specialist.drop_jobs()


async def test_without_a_sanction_the_profile_is_edited_as_before(worker: AsyncContainer) -> None:
    specialist = Specialist(worker)
    await specialist.publish()
    try:
        await specialist.call(
            EditProfile,
            EditProfileCommand(actor_id=specialist.user_id, headline="Электрик и сантехник"),
        )
        await specialist.call(
            SetAvailability, SetAvailabilityCommand(actor_id=specialist.user_id, until=None)
        )

        headline = await specialist.scalar(
            "SELECT headline FROM specialists.profiles WHERE id = :id", id=specialist.profile_id
        )
        assert headline == "Электрик и сантехник"
    finally:
        await specialist.drop_jobs()
