"""Согласия, единая точка «можно ли», санкции через фасад и город с намерением (1.4a).

Use cases и фасад на PostgreSQL в откатываемой транзакции; фасад geo и версии документов
из client-config — фейки (ADR-0020 §11).
"""

from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, text

from app.modules.identity.api import Action, RestrictionIn
from app.modules.identity.application.use_cases.accept_consents import AcceptConsentsCommand
from app.modules.identity.application.use_cases.authenticate_telegram import (
    AuthenticateTelegramCommand,
)
from app.modules.identity.application.use_cases.update_profile import UpdateProfileCommand
from app.modules.identity.domain.consent import ConsentDocument
from app.modules.identity.domain.restriction import RestrictionKind, RestrictionSource
from app.modules.identity.domain.user import UserIntent
from app.modules.identity.errors import (
    AccountDeletedError,
    CityNotAvailableError,
    ConsentRequiredError,
    InvalidRestrictionError,
    LegalVersionOutdatedError,
    UnknownCityError,
    UserNotFoundError,
)
from app.modules.identity.infrastructure.models import ConsentRow, RestrictionRow
from app.modules.identity.infrastructure.repositories import SqlConsentRepository
from app.modules.identity.tests.fakes import a_city
from app.platform.contracts.events.identity import (
    OnboardingCompleted,
    UserRestricted,
    UserUpdated,
)
from app.platform.db.errors import WriteOutsideUnitOfWorkError
from app.platform.kernel.errors import RestrictedError
from app.platform.kernel.ids import CaseId, CityId, UserId, new_id
from app.platform.kernel.principal import Platform
from app.platform.queue.dispatcher import EventRegistry
from app.platform.queue.port import TaskRef
from app.platform.testing.queue import queued_tasks

from .conftest import Identity, telegram_profile

pytestmark = pytest.mark.integration

CREATING = (Action.POST, Action.RESPOND, Action.MESSAGE)


async def registered(identity: Identity) -> UserId:
    result = await identity.authenticate(AuthenticateTelegramCommand(profile=telegram_profile()))
    return result.tokens.user_id


def tick(
    user_id: UserId, terms: str = "draft-1", privacy: str = "draft-1"
) -> AcceptConsentsCommand:
    return AcceptConsentsCommand(
        actor_id=user_id,
        terms_version=terms,
        privacy_version=privacy,
        source=Platform.TMA,
        ip="10.1.2.3",
    )


async def consent_rows(identity: Identity, user_id: UserId) -> list[tuple[str, str, str, str]]:
    c = ConsentRow.__table__.c
    rows = await identity.session.execute(
        select(c.document, c.version, c.source, c.ip)
        .where(c.user_id == user_id)
        .order_by(c.document, c.version)
    )
    return [(r.document.value, r.version, r.source.value, str(r.ip)) for r in rows]


# --- AcceptConsents -----------------------------------------------------------------------


async def test_one_tick_records_terms_privacy_and_age_once(identity: Identity) -> None:
    user_id = await registered(identity)
    assert await identity.accept_consents(tick(user_id)) == 3
    assert await identity.accept_consents(tick(user_id)) == 0
    assert await consent_rows(identity, user_id) == [
        ("age_18", "draft-1", "tma", "10.1.2.3"),
        ("privacy", "draft-1", "tma", "10.1.2.3"),
        ("terms", "draft-1", "tma", "10.1.2.3"),
    ]


async def test_new_terms_version_is_a_new_record(identity: Identity) -> None:
    user_id = await registered(identity)
    await identity.accept_consents(tick(user_id))
    identity.legal.versions["terms"] = "draft-2"

    with pytest.raises(LegalVersionOutdatedError):
        await identity.accept_consents(tick(user_id))
    assert await identity.accept_consents(tick(user_id, terms="draft-2")) == 2
    documents = [(d, v) for d, v, _, _ in await consent_rows(identity, user_id)]
    assert documents == [
        ("age_18", "draft-1"),
        ("age_18", "draft-2"),
        ("privacy", "draft-1"),
        ("terms", "draft-1"),
        ("terms", "draft-2"),
    ]


async def test_deleted_account_cannot_consent(identity: Identity) -> None:
    user_id = await registered(identity)
    async with identity.uow:
        user = await identity.users.get(user_id)
        user.delete(by=user.id, now=identity.clock.now())
        await identity.users.save(user)
    with pytest.raises(AccountDeletedError):
        await identity.accept_consents(tick(user_id))
    assert await consent_rows(identity, user_id) == []


# --- «можно ли» ---------------------------------------------------------------------------


async def test_creating_actions_need_current_consent(identity: Identity) -> None:
    user_id = await registered(identity)
    await identity.facade.ensure_allowed(user_id, Action.LOGIN)
    for action in CREATING:
        with pytest.raises(ConsentRequiredError) as caught:
            await identity.facade.ensure_allowed(user_id, action)
        assert caught.value.params == {"documents": ["age_18", "privacy", "terms"]}
    view = await identity.access.view(user_id)
    assert view.consent_required
    assert view.allowed == frozenset({Action.LOGIN})
    assert view.consents == {}

    await identity.accept_consents(tick(user_id))
    for action in CREATING:
        await identity.facade.ensure_allowed(user_id, action)
    view = await identity.access.view(user_id)
    assert not view.consent_required
    assert view.allowed == frozenset(Action)
    assert view.consents == {
        ConsentDocument.TERMS: "draft-1",
        ConsentDocument.PRIVACY: "draft-1",
        ConsentDocument.AGE_18: "draft-1",
    }

    identity.legal.versions["privacy"] = "draft-2"
    with pytest.raises(ConsentRequiredError) as caught:
        await identity.facade.ensure_allowed(user_id, Action.POST)
    assert caught.value.params == {"documents": ["privacy"]}
    assert (await identity.access.view(user_id)).consent_required


async def test_restriction_is_checked_before_consent(identity: Identity) -> None:
    user_id = await registered(identity)
    await identity.restrict(user_id, RestrictionKind.POSTING_BLOCKED)
    with pytest.raises(RestrictedError):
        await identity.facade.ensure_allowed(user_id, Action.POST)
    with pytest.raises(ConsentRequiredError):
        await identity.facade.ensure_allowed(user_id, Action.RESPOND)

    await identity.accept_consents(tick(user_id))
    view = await identity.access.view(user_id)
    assert view.allowed == {Action.LOGIN, Action.RESPOND, Action.MESSAGE}
    assert not view.consent_required


# --- санкция через фасад ------------------------------------------------------------------


async def test_moderation_restricts_through_facade(
    identity: Identity, events: EventRegistry
) -> None:
    on_restricted = TaskRef("test.on_user_restricted", UserRestricted)
    events.subscribe(UserRestricted, on_restricted)
    user_id = await registered(identity)
    moderator = await registered(identity)
    await identity.accept_consents(tick(user_id))
    case_id = CaseId(new_id())
    until = identity.clock.now() + timedelta(days=30)

    async with identity.uow:
        restriction_id = await identity.facade.restrict(
            RestrictionIn(
                user_id=user_id,
                kind=RestrictionKind.RESPONDING_BLOCKED,
                reason_code="strike_2",
                ends_at=until,
                case_id=case_id,
                created_by=moderator,
            )
        )

    with pytest.raises(RestrictedError) as caught:
        await identity.facade.ensure_allowed(user_id, Action.RESPOND)
    assert (caught.value.restriction, caught.value.until) == ("responding_blocked", until)
    await identity.facade.ensure_allowed(user_id, Action.POST)

    r = RestrictionRow.__table__.c
    row = (
        await identity.session.execute(
            select(r.user_id, r.source, r.case_id, r.created_by, r.starts_at).where(
                r.id == restriction_id
            )
        )
    ).one()
    assert tuple(row) == (
        user_id,
        RestrictionSource.MODERATION,
        case_id,
        moderator,
        identity.clock.now(),
    )
    [task] = await queued_tasks(identity.session, on_restricted.name)
    assert task.payload["user_id"] == str(user_id)
    assert task.payload["restriction_id"] == str(restriction_id)
    assert (task.payload["kind"], task.payload["reason_code"]) == ("responding_blocked", "strike_2")
    assert task.payload["case_id"] == str(case_id)


async def test_restrict_needs_callers_transaction_and_valid_data(identity: Identity) -> None:
    user_id = await registered(identity)
    data = RestrictionIn(user_id=user_id, kind=RestrictionKind.BANNED, reason_code="rules.p0")
    with pytest.raises(WriteOutsideUnitOfWorkError):
        await identity.facade.restrict(data)
    with pytest.raises(InvalidRestrictionError):
        async with identity.uow:
            await identity.facade.restrict(
                RestrictionIn(user_id=user_id, kind=RestrictionKind.BANNED, reason_code="Бан")
            )
    with pytest.raises(UserNotFoundError):
        async with identity.uow:
            await identity.facade.restrict(
                RestrictionIn(
                    user_id=UserId(UUID(int=7)), kind=RestrictionKind.BANNED, reason_code="spam"
                )
            )
    await identity.facade.ensure_allowed(user_id, Action.LOGIN)


# --- город и намерение --------------------------------------------------------------------


async def seeded_city_id(identity: Identity, slug: str) -> CityId:
    city_id: int = (
        await identity.session.execute(
            text("SELECT id FROM geo.cities WHERE slug = :slug"), {"slug": slug}
        )
    ).scalar_one()
    return CityId(city_id)


async def test_intent_is_saved_with_user_updated_event(
    identity: Identity, events: EventRegistry
) -> None:
    on_updated = TaskRef("test.on_user_updated", UserUpdated)
    events.subscribe(UserUpdated, on_updated)
    user_id = await registered(identity)

    version = await identity.update_profile(
        UpdateProfileCommand(actor_id=user_id, intent=UserIntent.PRO, expected_version=1)
    )

    assert version == 2
    async with identity.uow:
        user = await identity.users.get(user_id)
    assert (user.intent, user.home_city_id) == (UserIntent.PRO, None)
    [task] = await queued_tasks(identity.session, on_updated.name)
    assert (task.payload["user_id"], task.payload["fields"]) == (str(user_id), ["intent"])


@pytest.mark.usefixtures("geo_seeded")
async def test_city_is_checked_through_geo_facade(identity: Identity) -> None:
    user_id = await registered(identity)
    novi_sad = identity.geo.add(a_city(await seeded_city_id(identity, "novi-sad")))
    belgrade = identity.geo.add(
        a_city(await seeded_city_id(identity, "beograd"), slug="beograd", active=False)
    )

    with pytest.raises(UnknownCityError):
        await identity.update_profile(
            UpdateProfileCommand(actor_id=user_id, home_city_id=CityId(999_999))
        )
    with pytest.raises(CityNotAvailableError):
        await identity.update_profile(
            UpdateProfileCommand(actor_id=user_id, home_city_id=belgrade.id)
        )
    version = await identity.update_profile(
        UpdateProfileCommand(actor_id=user_id, home_city_id=novi_sad.id, expected_version=1)
    )
    assert version == 2

    identity.geo.add(a_city(novi_sad.id, active=False))  # город стал «скоро» после выбора
    await identity.update_profile(
        UpdateProfileCommand(actor_id=user_id, home_city_id=novi_sad.id, intent=UserIntent.CLIENT)
    )
    async with identity.uow:
        user = await identity.users.get(user_id)
    assert (user.home_city_id, user.intent) == (novi_sad.id, UserIntent.CLIENT)


async def test_city_missing_in_database_is_unknown(identity: Identity) -> None:
    """Фасад geo сказал «есть», а строки нет (удалили между проверкой и записью): FK."""
    user_id = await registered(identity)
    ghost = identity.geo.add(a_city(2_000_000_000))
    with pytest.raises(UnknownCityError):
        await identity.update_profile(UpdateProfileCommand(actor_id=user_id, home_city_id=ghost.id))
    async with identity.uow:
        assert (await identity.users.get(user_id)).home_city_id is None


# --- OnboardingCompleted (1.7) -----------------------------------------------------------

ON_ONBOARDED = TaskRef("test.onboarding_completed", OnboardingCompleted)


async def onboarded(identity: Identity, user_id: UserId) -> list[dict[str, object]]:
    tasks = await queued_tasks(identity.session, ON_ONBOARDED.name)
    return [t.payload for t in tasks if t.payload.get("user_id") == str(user_id)]


@pytest.mark.usefixtures("geo_seeded")
async def test_first_consent_completes_onboarding_once(
    identity: Identity, events: EventRegistry
) -> None:
    events.subscribe(OnboardingCompleted, ON_ONBOARDED)
    user_id = await registered(identity)
    novi_sad = identity.geo.add(a_city(await seeded_city_id(identity, "novi-sad")))
    await identity.update_profile(
        UpdateProfileCommand(actor_id=user_id, home_city_id=novi_sad.id, intent=UserIntent.PRO)
    )

    await identity.accept_consents(tick(user_id))
    await identity.accept_consents(tick(user_id))  # повтор
    identity.legal.versions["terms"] = "draft-2"
    await identity.accept_consents(tick(user_id, terms="draft-2"))  # новая редакция

    payloads = await onboarded(identity, user_id)
    assert [(p["intent"], p["home_city_id"]) for p in payloads] == [("pro", novi_sad.id)]


async def test_onboarding_without_profile_steps_carries_no_intent_or_city(
    identity: Identity, events: EventRegistry
) -> None:
    events.subscribe(OnboardingCompleted, ON_ONBOARDED)
    user_id = await registered(identity)

    await identity.accept_consents(tick(user_id))

    [payload] = await onboarded(identity, user_id)
    assert (payload["intent"], payload["home_city_id"]) == (None, None)


async def test_earlier_v1_consent_does_not_hide_onboarding(
    identity: Identity, events: EventRegistry
) -> None:
    """Согласия v1 (геолокация, аналитика) даются раньше S02c: онбординг — первая галочка
    S02c, а не первое согласие вообще."""
    events.subscribe(OnboardingCompleted, ON_ONBOARDED)
    user_id = await registered(identity)
    consents = SqlConsentRepository(identity.session, identity.uow)
    async with identity.uow:
        await consents.grant(
            user_id,
            {ConsentDocument.PRECISE_LOCATION: "draft-1"},
            source=Platform.TMA,
            ip=None,
            now=identity.clock.now(),
        )

    await identity.accept_consents(tick(user_id))

    assert len(await onboarded(identity, user_id)) == 1
