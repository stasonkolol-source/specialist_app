"""Политики identity (ADR-0020 §2): согласия, нужные для действий, и уровень доверия."""

from collections.abc import Iterable, Mapping, Sequence
from datetime import timedelta
from typing import Final

from app.modules.identity.domain.consent import ONE_TICK, Consent, ConsentDocument
from app.modules.identity.domain.trust import CLEAN_PERIOD, TrustLevel, TrustRule, TrustSignals
from app.modules.identity.errors import (
    LegalVersionOutdatedError,
    LegalVersionsUnavailableError,
)

# --- согласия ------------------------------------------------------------------------------


def required_consents(legal_versions: Mapping[str, str]) -> dict[ConsentDocument, str]:
    """Действующие версии документов одной галочки из client-config `legal_versions`.

    18+ подтверждается в правилах, поэтому его версия — версия правил. Документа без
    версии в конфигурации в ответе нет.
    """
    required: dict[ConsentDocument, str] = {}
    if terms := legal_versions.get(ConsentDocument.TERMS):
        required[ConsentDocument.TERMS] = terms
        required[ConsentDocument.AGE_18] = terms
    if privacy := legal_versions.get(ConsentDocument.PRIVACY):
        required[ConsentDocument.PRIVACY] = privacy
    return required


def one_tick_consents(
    legal_versions: Mapping[str, str], *, terms_version: str, privacy_version: str
) -> dict[ConsentDocument, str]:
    """Что записать по галочке S02c: версии, которые видел пользователь, должны быть
    действующими — иначе он принял бы не тот текст."""
    required = required_consents(legal_versions)
    if ConsentDocument.TERMS not in required or ConsentDocument.PRIVACY not in required:
        raise LegalVersionsUnavailableError
    for document, seen in (
        (ConsentDocument.TERMS, terms_version),
        (ConsentDocument.PRIVACY, privacy_version),
    ):
        if seen != required[document]:
            raise LegalVersionOutdatedError(document=document.value, current=required[document])
    return required


def missing_consents(
    accepted: Iterable[Consent], required: Mapping[ConsentDocument, str]
) -> frozenset[ConsentDocument]:
    """Документы одной галочки без действующего согласия.

    Версия из конфигурации должна совпасть: новая редакция правил требует новой галочки.
    Если версии документа в конфигурации нет, хватает согласия с любой версией.
    """
    versions = {(c.document, c.version) for c in accepted}
    documents = {document for document, _ in versions}
    return frozenset(
        document
        for document in ONE_TICK
        if (
            (document, required[document]) not in versions
            if document in required
            else document not in documents
        )
    )


def accepted_versions(accepted: Iterable[Consent]) -> dict[ConsentDocument, str]:
    """Последняя принятая версия каждого документа (для GET /me)."""
    latest: dict[ConsentDocument, Consent] = {}
    for consent in accepted:
        known = latest.get(consent.document)
        if known is None or consent.granted_at >= known.granted_at:
            latest[consent.document] = consent
    return {document: consent.version for document, consent in latest.items()}


# --- уровень доверия -----------------------------------------------------------------------


def _clean_for(signals: TrustSignals) -> timedelta:
    """Сколько пользователь живёт без нарушений: с регистрации или с последнего нарушения."""
    if signals.penalized_ago is None:
        return signals.account_age
    return min(signals.account_age, signals.penalized_ago)


def clean_period_passed(signals: TrustSignals) -> TrustLevel:
    """≥ 14 дней на площадке без подтверждённых жалоб и санкций → базовый (ADR-0016 §2)."""
    return TrustLevel.BASIC if _clean_for(signals) >= CLEAN_PERIOD else TrustLevel.NEW


def no_active_sanctions(signals: TrustSignals) -> TrustLevel:
    """Пока действует санкция, уровень — 0: лимиты и модерация как у нового аккаунта."""
    return TrustLevel.NEW if signals.active_sanctions else TrustLevel.TRUSTED


def no_recent_violation(signals: TrustSignals) -> TrustLevel:
    """Нарушение за последние 14 дней опускает уровень до 0 (2.5a)."""
    recent = signals.penalized_ago is not None and signals.penalized_ago < CLEAN_PERIOD
    return TrustLevel.NEW if recent else TrustLevel.TRUSTED


PROMOTIONS: Final[Sequence[TrustRule]] = (clean_period_passed,)
"""Правила повышения (§13.2): 14 дней без жалоб → 1 (2.5a); телефон → 1 (2.9),
3 сделки без жалоб → 2 (6.1a) — в своих шагах."""

CAPS: Final[Sequence[TrustRule]] = (no_active_sanctions, no_recent_violation)
"""Потолки: действующая санкция и нарушение за 14 дней опускают уровень до 0 (2.5a)."""


def trust_level(
    signals: TrustSignals,
    *,
    promotions: Sequence[TrustRule] = PROMOTIONS,
    caps: Sequence[TrustRule] = CAPS,
) -> TrustLevel:
    """Уровень доверия: лучшее из повышений, но не выше самого низкого потолка."""
    level = max((rule(signals) for rule in promotions), default=TrustLevel.NEW)
    return min((level, *(cap(signals) for cap in caps)))
