"""Лист ожидания города «скоро» (S02a): «Сообщить о запуске» включает opt-in группу
`city_launch` в обоих каналах — как «Вещи» (S58) — и даёт одно событие CityWaitlistJoined с
городом; повтор ничего не меняет; открытый или неизвестный город — 422."""

import pytest

from app.modules.notifications.application.use_cases.join_city_waitlist import (
    JoinCityWaitlistCommand,
)
from app.modules.notifications.domain.catalog import Channel, EventGroup
from app.modules.notifications.errors import CityNotUpcomingError
from app.modules.notifications.tests.integration.conftest import Notifications
from app.platform.kernel.ids import CityId

pytestmark = pytest.mark.integration

NOVI_SAD, BEOGRAD = CityId(1), CityId(2)


async def test_upcoming_city_waitlist_turns_on_the_launch_group_once(
    notifications: Notifications,
) -> None:
    user_id = await notifications.user_with_bot()

    view = await notifications.join_city(JoinCityWaitlistCommand(user_id=user_id, city_id=BEOGRAD))
    again = await notifications.join_city(JoinCityWaitlistCommand(user_id=user_id, city_id=BEOGRAD))

    for channel in Channel:
        assert view.settings.preferences.allows(EventGroup.CITY_LAUNCH, channel)
        assert again.settings.preferences.allows(EventGroup.CITY_LAUNCH, channel)
    # остальные группы не тронуты: «Вещи» и новости — по-прежнему только по согласию
    stored = (await notifications.queries.settings(user_id)).settings.preferences
    assert stored.allows(EventGroup.CITY_LAUNCH, Channel.TELEGRAM)
    assert not stored.allows(EventGroup.GOODS_LAUNCH, Channel.TELEGRAM)
    assert stored.allows(EventGroup.RESPONSES, Channel.TELEGRAM)
    joined = await notifications.city_waitlisted(user_id)
    assert [(e["city_id"], e["bot_writable"]) for e in joined] == [(BEOGRAD, True)]


async def test_waitlist_without_bot_says_so(notifications: Notifications) -> None:
    user_id, _chat_id = await notifications.user_with_chat()  # боту писать ещё нельзя

    await notifications.join_city(JoinCityWaitlistCommand(user_id=user_id, city_id=BEOGRAD))

    assert [e["bot_writable"] for e in await notifications.city_waitlisted(user_id)] == [False]


@pytest.mark.parametrize("city_id", [NOVI_SAD, CityId(404)])
async def test_only_upcoming_cities_have_a_waitlist(
    notifications: Notifications, city_id: CityId
) -> None:
    user_id = await notifications.user_with_bot()

    with pytest.raises(CityNotUpcomingError):
        await notifications.join_city(JoinCityWaitlistCommand(user_id=user_id, city_id=city_id))

    assert await notifications.city_waitlisted(user_id) == []
