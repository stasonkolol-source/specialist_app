"""Политики identity: согласия одной галочки и каркас уровня доверия (DEVELOPMENT_PLAN 1.4a)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.identity.domain.consent import Consent, ConsentDocument
from app.modules.identity.domain.policies import (
    accepted_versions,
    missing_consents,
    one_tick_consents,
    required_consents,
    trust_level,
)
from app.modules.identity.domain.trust import TrustLevel, TrustSignals
from app.modules.identity.errors import (
    LegalVersionOutdatedError,
    LegalVersionsUnavailableError,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
LEGAL = {"terms": "draft-1", "privacy": "draft-1", "moderation": "draft-1"}
TERMS, PRIVACY, AGE_18 = ConsentDocument.TERMS, ConsentDocument.PRIVACY, ConsentDocument.AGE_18


def consent(document: ConsentDocument, version: str, *, days: int = 0) -> Consent:
    return Consent(document=document, version=version, granted_at=NOW + timedelta(days=days))


def one_tick(version: str = "draft-1", *, days: int = 0) -> list[Consent]:
    return [consent(d, version, days=days) for d in (TERMS, PRIVACY, AGE_18)]


# --- согласия ------------------------------------------------------------------------------


def test_age_confirmation_follows_terms_version() -> None:
    assert required_consents({"terms": "v2", "privacy": "p1"}) == {
        TERMS: "v2",
        AGE_18: "v2",
        PRIVACY: "p1",
    }
    assert required_consents({"privacy": "p1"}) == {PRIVACY: "p1"}
    assert required_consents({"terms": ""}) == {}


def test_one_tick_records_terms_privacy_and_age() -> None:
    assert one_tick_consents(LEGAL, terms_version="draft-1", privacy_version="draft-1") == {
        TERMS: "draft-1",
        PRIVACY: "draft-1",
        AGE_18: "draft-1",
    }


@pytest.mark.parametrize(
    ("terms", "privacy", "document"),
    [("draft-0", "draft-1", "terms"), ("draft-1", "v2", "privacy")],
)
def test_one_tick_refuses_version_the_user_did_not_see(
    terms: str, privacy: str, document: str
) -> None:
    with pytest.raises(LegalVersionOutdatedError) as caught:
        one_tick_consents(LEGAL, terms_version=terms, privacy_version=privacy)
    assert caught.value.params == {"document": document, "current": "draft-1"}


@pytest.mark.parametrize("legal", [{}, {"terms": "draft-1"}, {"privacy": "draft-1"}])
def test_one_tick_needs_configured_versions(legal: dict[str, str]) -> None:
    with pytest.raises(LegalVersionsUnavailableError):
        one_tick_consents(legal, terms_version="draft-1", privacy_version="draft-1")


def test_missing_consents_compare_current_versions() -> None:
    required = required_consents(LEGAL)
    assert missing_consents([], required) == {TERMS, PRIVACY, AGE_18}
    assert missing_consents(one_tick(), required) == frozenset()
    assert missing_consents(one_tick()[:2], required) == {AGE_18}
    newer_terms = required_consents({"terms": "draft-2", "privacy": "draft-1"})
    assert missing_consents(one_tick(), newer_terms) == {TERMS, AGE_18}


def test_without_configured_version_any_accepted_version_counts() -> None:
    assert missing_consents(one_tick("old"), {}) == frozenset()
    assert missing_consents([consent(TERMS, "old")], {}) == {PRIVACY, AGE_18}


def test_accepted_versions_show_latest_per_document() -> None:
    accepted = [*one_tick("draft-1"), consent(TERMS, "draft-2", days=3)]
    assert accepted_versions(accepted) == {TERMS: "draft-2", PRIVACY: "draft-1", AGE_18: "draft-1"}
    assert accepted_versions([]) == {}


# --- уровень доверия -----------------------------------------------------------------------

SIGNALS = TrustSignals(account_age=timedelta(days=30), phone_verified=True, completed_deals=5)


def signals(
    *,
    age: int,
    penalized: int | None = None,
    sanctions: int = 0,
    phone: bool = False,
    deals: int = 0,
) -> TrustSignals:
    return TrustSignals(
        account_age=timedelta(days=age),
        phone_verified=phone,
        penalized_ago=timedelta(days=penalized) if penalized is not None else None,
        active_sanctions=sanctions,
        completed_deals=deals,
    )


@pytest.mark.parametrize(
    ("given", "level"),
    [
        (signals(age=13), TrustLevel.NEW),  # новичок
        (signals(age=14), TrustLevel.BASIC),  # 14 дней без жалоб (ADR-0016 §2)
        (signals(age=400, penalized=3), TrustLevel.NEW),  # нарушение опускает до 0
        (signals(age=400, penalized=13), TrustLevel.NEW),
        (signals(age=400, penalized=14), TrustLevel.BASIC),  # 14 дней после нарушения
        (signals(age=400, sanctions=1), TrustLevel.NEW),  # пока действует санкция
        (signals(age=400, penalized=100, sanctions=1), TrustLevel.NEW),
        (signals(age=5, phone=True), TrustLevel.NEW),  # телефон повысит в v1
        # 6.1a: три завершённые сделки — проверенный, жалобы и санкции держат потолки
        (signals(age=5, deals=2), TrustLevel.NEW),
        (signals(age=30, deals=2), TrustLevel.BASIC),
        (signals(age=5, deals=3), TrustLevel.VERIFIED),
        (signals(age=400, deals=12), TrustLevel.VERIFIED),  # 3 (доверенный) — с KYC в v1
        (signals(age=400, deals=5, penalized=3), TrustLevel.NEW),
        (signals(age=400, deals=5, penalized=30), TrustLevel.VERIFIED),
        (signals(age=400, deals=5, sanctions=1), TrustLevel.NEW),
    ],
)
def test_trust_level_rules(given: TrustSignals, level: TrustLevel) -> None:
    assert trust_level(given) is level


def test_trust_level_takes_best_promotion_under_lowest_cap() -> None:
    def phone(signals: TrustSignals) -> TrustLevel:
        return TrustLevel.BASIC if signals.phone_verified else TrustLevel.NEW

    def deals(signals: TrustSignals) -> TrustLevel:
        return TrustLevel.VERIFIED if signals.completed_deals >= 3 else TrustLevel.NEW

    def sanction(signals: TrustSignals) -> TrustLevel:
        return TrustLevel.NEW if signals.active_sanctions else TrustLevel.TRUSTED

    assert trust_level(SIGNALS, promotions=(phone, deals)) is TrustLevel.VERIFIED
    assert trust_level(SIGNALS, promotions=(phone, deals), caps=(sanction,)) is TrustLevel.VERIFIED
    sanctioned = TrustSignals(
        account_age=timedelta(days=30), phone_verified=True, active_sanctions=1
    )
    assert trust_level(sanctioned, promotions=(phone,), caps=(sanction,)) is TrustLevel.NEW
