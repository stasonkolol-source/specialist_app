"""«Подтвердить телефон» (POST /me/phone): подписанный контакт → бейдж и уровень доверия 1.

Use case на PostgreSQL в откатываемой транзакции; подпись — настоящий InitDataVerifier с
токеном теста, часы — FakeClock. Номера случайные: индекс «один номер — один аккаунт» общий
для всей базы тестов.
"""

import json
from datetime import timedelta
from urllib.parse import urlencode

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.modules.identity.application.trust import TrustRecalculation
from app.modules.identity.application.use_cases.authenticate_telegram import (
    AuthenticateTelegramCommand,
)
from app.modules.identity.application.use_cases.verify_phone import (
    PHONE_VERIFICATION_FLAG,
    VerifyPhone,
    VerifyPhoneCommand,
)
from app.modules.identity.domain.trust import TrustLevel
from app.modules.identity.errors import (
    InvalidPhoneContactError,
    PhoneTakenError,
    PhoneVerificationUnavailableError,
)
from app.modules.identity.infrastructure.contacts import TelegramPhoneContacts
from app.modules.identity.infrastructure.models import UserRow
from app.platform.contracts.events.identity import PhoneVerified
from app.platform.kernel.ids import UserId, new_id
from app.platform.queue.dispatcher import EventRegistry
from app.platform.queue.port import TaskRef
from app.platform.security.initdata import InitDataVerifier, sign
from app.platform.testing.config import FakeFeatureFlags
from app.platform.testing.queue import queued_tasks

from .conftest import Identity, telegram_profile

pytestmark = pytest.mark.integration

BOT_TOKEN = "7000000001:test-phone-token"  # noqa: S105 — токен теста, не секрет
ON_PHONE = TaskRef("test.phone_verified", PhoneVerified)


def a_phone() -> str:
    return f"+38164{new_id().int % 10_000_000:07d}"


def contact(
    identity: Identity, telegram_id: int, phone: str, *, age: timedelta = timedelta(0)
) -> str:
    shared = {"user_id": telegram_id, "phone_number": phone.removeprefix("+"), "first_name": "A"}
    fields = {
        "contact": json.dumps(shared),
        "auth_date": str(int((identity.clock.now() - age).timestamp())),
    }
    return urlencode(fields | {"hash": sign(fields, BOT_TOKEN)})


def verify_phone(identity: Identity, *, enabled: bool = True) -> VerifyPhone:
    verifier = InitDataVerifier(SecretStr(BOT_TOKEN), identity.clock)
    flags = FakeFeatureFlags(enabled={PHONE_VERIFICATION_FLAG} if enabled else set())
    return VerifyPhone(
        identity.uow,
        identity.users,
        TelegramPhoneContacts(verifier),
        TrustRecalculation(identity.query),
        flags,
        identity.clock,
    )


async def registered(identity: Identity) -> tuple[UserId, int]:
    profile = telegram_profile()
    result = await identity.authenticate(AuthenticateTelegramCommand(profile=profile))
    return result.tokens.user_id, profile.id


async def stored(identity: Identity, user_id: UserId) -> tuple[str | None, bool, int]:
    u = UserRow.__table__.c
    row = (
        await identity.session.execute(
            select(u.phone_e164, u.phone_verified_at, u.trust_level).where(u.id == user_id)
        )
    ).one()
    return row.phone_e164, row.phone_verified_at is not None, row.trust_level


async def test_own_contact_verifies_the_phone_and_lifts_trust(
    identity: Identity, events: EventRegistry
) -> None:
    events.subscribe(PhoneVerified, ON_PHONE)
    user_id, telegram_id = await registered(identity)
    phone = a_phone()
    verify = verify_phone(identity)

    assert await verify(
        VerifyPhoneCommand(actor_id=user_id, contact=contact(identity, telegram_id, phone))
    )
    assert await stored(identity, user_id) == (phone, True, TrustLevel.BASIC)
    me = await identity.query.user_summary(user_id)
    assert me is not None
    assert me.phone_verified

    # повтор тем же номером — без изменений и без второго события
    again = contact(identity, telegram_id, phone)
    assert not await verify(VerifyPhoneCommand(actor_id=user_id, contact=again))
    payloads = [t.payload for t in await queued_tasks(identity.session, ON_PHONE.name)]
    assert [p["user_id"] for p in payloads] == [str(user_id)]
    assert all(phone.removeprefix("+") not in json.dumps(p) for p in payloads)


async def test_switched_off_verification_writes_nothing(
    identity: Identity, events: EventRegistry
) -> None:
    """Флаг выключен (до редакции 2 политики) — 404 до проверки контакта, ничего не пишется."""
    events.subscribe(PhoneVerified, ON_PHONE)
    user_id, telegram_id = await registered(identity)
    raw = contact(identity, telegram_id, a_phone())

    with pytest.raises(PhoneVerificationUnavailableError):
        await verify_phone(identity, enabled=False)(
            VerifyPhoneCommand(actor_id=user_id, contact=raw)
        )

    assert await stored(identity, user_id) == (None, False, TrustLevel.NEW)
    assert await queued_tasks(identity.session, ON_PHONE.name) == []


async def test_number_of_another_account_is_taken(identity: Identity) -> None:
    first, first_tg = await registered(identity)
    second, second_tg = await registered(identity)
    phone = a_phone()
    verify = verify_phone(identity)
    await verify(VerifyPhoneCommand(actor_id=first, contact=contact(identity, first_tg, phone)))

    with pytest.raises(PhoneTakenError):
        await verify(
            VerifyPhoneCommand(actor_id=second, contact=contact(identity, second_tg, phone))
        )
    assert await stored(identity, second) == (None, False, TrustLevel.NEW)


@pytest.mark.parametrize(
    ("reason", "tamper"),
    [
        ("not_own", "other_user"),
        ("signature", "bad_hash"),
        ("expired", "old"),
    ],
)
async def test_foreign_forged_or_stale_contact_is_refused(
    identity: Identity, reason: str, tamper: str
) -> None:
    user_id, telegram_id = await registered(identity)
    phone = a_phone()
    if tamper == "other_user":
        raw = contact(identity, telegram_id + 1, phone)
    elif tamper == "old":
        raw = contact(identity, telegram_id, phone, age=timedelta(hours=2))
    else:
        raw = contact(identity, telegram_id, phone)[:-4] + "0000"

    with pytest.raises(InvalidPhoneContactError) as refused:
        await verify_phone(identity)(VerifyPhoneCommand(actor_id=user_id, contact=raw))

    assert refused.value.params["reason"] == reason
    assert await stored(identity, user_id) == (None, False, TrustLevel.NEW)


async def test_recent_violation_keeps_level_zero_but_the_badge_is_set(
    identity: Identity,
) -> None:
    user_id, telegram_id = await registered(identity)
    async with identity.uow:
        await identity.facade.record_violation(user_id)

    await verify_phone(identity)(
        VerifyPhoneCommand(actor_id=user_id, contact=contact(identity, telegram_id, a_phone()))
    )

    _, verified, level = await stored(identity, user_id)
    assert (verified, level) == (True, TrustLevel.NEW)


async def test_deleted_account_frees_the_number(identity: Identity) -> None:
    """Удалённый аккаунт номер не держит (частичный индекс, `forget`): хэш номера для антифрода
    хранится отдельно, 12 месяцев (deleted_identity_hashes)."""
    first, first_tg = await registered(identity)
    second, second_tg = await registered(identity)
    phone = a_phone()
    verify = verify_phone(identity)
    await verify(VerifyPhoneCommand(actor_id=first, contact=contact(identity, first_tg, phone)))
    async with identity.uow:
        user = await identity.users.get_for_update(first)
        user.forget(now=identity.clock.now())
        await identity.users.save(user)

    assert await verify(
        VerifyPhoneCommand(actor_id=second, contact=contact(identity, second_tg, phone))
    )
