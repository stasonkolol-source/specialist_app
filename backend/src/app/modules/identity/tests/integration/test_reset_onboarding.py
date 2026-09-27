"""`cli dev-reset-user`: онбординг заново для владельца dev-бота (DEVELOPMENT_PLAN 1.5b).

Use case на PostgreSQL в откатываемой транзакции: после сброса /me снова требует S02a
(нет города) и S02c (согласия отозваны), журнал согласий остаётся.
"""

import pytest
from sqlalchemy import select, text

from app.modules.identity.application.use_cases.accept_consents import AcceptConsentsCommand
from app.modules.identity.application.use_cases.authenticate_telegram import (
    AuthenticateTelegramCommand,
)
from app.modules.identity.application.use_cases.reset_onboarding import (
    ResetOnboarding,
    ResetOnboardingCommand,
)
from app.modules.identity.application.use_cases.update_profile import UpdateProfileCommand
from app.modules.identity.domain.user import UserIntent
from app.modules.identity.infrastructure.models import ConsentRow
from app.modules.identity.infrastructure.repositories import SqlConsentRepository
from app.modules.identity.tests.fakes import a_city
from app.platform.kernel.ids import CityId, UserId
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Platform

from .conftest import Identity, telegram_profile

pytestmark = pytest.mark.integration

TELEGRAM_ID = 279_000_777


def reset_of(identity: Identity) -> ResetOnboarding:
    consents = SqlConsentRepository(identity.session, identity.uow)
    return ResetOnboarding(identity.uow, identity.users, consents, identity.clock)


async def onboarded(identity: Identity) -> UserId:
    """Пользователь прошёл S02a–c: sr-Cyrl, Нови-Сад, «Я специалист», согласия draft-1."""
    result = await identity.authenticate(
        AuthenticateTelegramCommand(profile=telegram_profile(id=TELEGRAM_ID, language_code="ru"))
    )
    user_id = result.tokens.user_id
    city_id: int = (
        await identity.session.execute(text("SELECT id FROM geo.cities WHERE slug = 'novi-sad'"))
    ).scalar_one()
    identity.geo.add(a_city(city_id))
    await identity.update_profile(
        UpdateProfileCommand(
            actor_id=user_id,
            ui_locale=Locale.SR_CYRL,
            home_city_id=CityId(city_id),
            intent=UserIntent.PRO,
        )
    )
    await identity.accept_consents(
        AcceptConsentsCommand(
            actor_id=user_id,
            terms_version="draft-1",
            privacy_version="draft-1",
            source=Platform.TMA,
        )
    )
    return user_id


@pytest.mark.usefixtures("geo_seeded")
async def test_reset_starts_the_onboarding_again_and_keeps_the_consent_journal(
    identity: Identity,
) -> None:
    user_id = await onboarded(identity)
    assert not (await identity.access.view(user_id)).consent_required

    result = await reset_of(identity)(ResetOnboardingCommand(telegram_id=TELEGRAM_ID))

    assert result is not None
    assert (result.user_id, result.withdrawn_consents) == (user_id, 3)
    me = await identity.query.me(user_id)
    assert me is not None
    # язык — снова из клиента Telegram (language_code=ru), как при регистрации
    assert (me.home_city_id, me.intent, me.ui_locale) == (None, None, Locale.RU)
    assert (await identity.access.view(user_id)).consent_required
    c = ConsentRow.__table__.c
    rows = await identity.session.execute(
        select(c.document, c.withdrawn_at).where(c.user_id == user_id)
    )
    journal = sorted((r.document.value, r.withdrawn_at is not None) for r in rows)
    assert journal == [("age_18", True), ("privacy", True), ("terms", True)]

    # повтор ничего не отзывает; после нового согласия запись — новая
    again = await reset_of(identity)(ResetOnboardingCommand(telegram_id=TELEGRAM_ID))
    assert again is not None
    assert again.withdrawn_consents == 0
    assert (
        await identity.accept_consents(
            AcceptConsentsCommand(
                actor_id=user_id,
                terms_version="draft-1",
                privacy_version="draft-1",
                source=Platform.TMA,
            )
        )
        == 3
    )


async def test_reset_of_an_unknown_telegram_user_changes_nothing(identity: Identity) -> None:
    assert await reset_of(identity)(ResetOnboardingCommand(telegram_id=1)) is None
