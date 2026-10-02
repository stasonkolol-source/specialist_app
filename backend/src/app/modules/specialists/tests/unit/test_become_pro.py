"""Переход в «Специалист»: прайс обязателен на проверке, но не у черновика."""

from datetime import UTC, datetime
from unittest.mock import create_autospec

import pytest

from app.modules.identity.api import IdentityApi
from app.modules.specialists.api import PriceList
from app.modules.specialists.application.ports import ProfileRepository
from app.modules.specialists.application.use_cases.become_pro import BecomePro, BecomeProCommand
from app.modules.specialists.domain.profile import Profile, ProfileKind, ProfileStatus
from app.modules.specialists.errors import ProfileIncompleteError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import CategoryId, CityId, UserId, new_id

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)


def casual_profile(status: ProfileStatus) -> Profile:
    profile = Profile.create(
        user_id=UserId(new_id()),
        kind=ProfileKind.CASUAL,
        display_name="Ана",
        city_id=CityId(1),
        now=NOW,
    )
    profile.edit(now=NOW, headline="Помощь с компьютером", work_modes=["remote"])
    profile.set_categories([CategoryId(57)], now=NOW)
    if status is not ProfileStatus.DRAFT:
        profile.submit(now=NOW)
    if status in (ProfileStatus.PUBLISHED, ProfileStatus.HIDDEN):
        profile.approve(now=NOW)
    if status is ProfileStatus.HIDDEN:
        profile.hide(now=NOW)
    return profile


@pytest.mark.parametrize(
    "status", [ProfileStatus.PENDING_REVIEW, ProfileStatus.PUBLISHED, ProfileStatus.HIDDEN]
)
async def test_becoming_pro_requires_prices_for_review(status: ProfileStatus) -> None:
    profile = casual_profile(status)
    profiles = create_autospec(ProfileRepository, instance=True)
    profiles.of_user.return_value = profile
    prices = create_autospec(PriceList, instance=True)
    prices.has_items.return_value = False
    uow = create_autospec(UnitOfWork, instance=True)
    clock = create_autospec(Clock, instance=True)
    clock.now.return_value = NOW
    become = BecomePro(uow, profiles, create_autospec(IdentityApi, instance=True), prices, clock)

    with pytest.raises(ProfileIncompleteError) as incomplete:
        await become(BecomeProCommand(actor_id=profile.user_id))

    assert incomplete.value.params == {"missing": ["services"]}
    profiles.save.assert_not_awaited()
    uow.add_event.assert_not_called()


@pytest.mark.parametrize("status", [ProfileStatus.DRAFT, ProfileStatus.PENDING_REVIEW])
async def test_becoming_pro_preserves_status_when_prices_are_sufficient(
    status: ProfileStatus,
) -> None:
    profile = casual_profile(status)
    profiles = create_autospec(ProfileRepository, instance=True)
    profiles.of_user.return_value = profile
    prices = create_autospec(PriceList, instance=True)
    prices.has_items.return_value = status is ProfileStatus.PENDING_REVIEW
    clock = create_autospec(Clock, instance=True)
    clock.now.return_value = NOW
    become = BecomePro(
        create_autospec(UnitOfWork, instance=True),
        profiles,
        create_autospec(IdentityApi, instance=True),
        prices,
        clock,
    )

    result = await become(BecomeProCommand(actor_id=profile.user_id))

    assert (result.kind, result.status, result.listed_in_catalog) == (ProfileKind.PRO, status, True)
    profiles.save.assert_awaited_once_with(profile)
    if status is ProfileStatus.DRAFT:
        prices.has_items.assert_not_awaited()
