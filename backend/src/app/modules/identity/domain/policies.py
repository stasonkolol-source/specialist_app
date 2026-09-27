"""Политики identity (ADR-0020 §2): согласия, нужные для действий, и уровень доверия."""

from collections.abc import Iterable, Mapping, Sequence
from typing import Final

from app.modules.identity.domain.consent import ONE_TICK, Consent, ConsentDocument
from app.modules.identity.domain.trust import TrustLevel, TrustRule, TrustSignals
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

PROMOTIONS: Final[Sequence[TrustRule]] = ()
"""Правила повышения (§13.2): телефон → 1 (2.9), 14 дней без жалоб → 1 (2.5a),
3 сделки без жалоб → 2 (6.1a)."""

CAPS: Final[Sequence[TrustRule]] = ()
"""Потолки: действующая санкция и подтверждённая жалоба понижают уровень (2.5a)."""


def trust_level(
    signals: TrustSignals,
    *,
    promotions: Sequence[TrustRule] = PROMOTIONS,
    caps: Sequence[TrustRule] = CAPS,
) -> TrustLevel:
    """Уровень доверия: лучшее из повышений, но не выше самого низкого потолка."""
    level = max((rule(signals) for rule in promotions), default=TrustLevel.NEW)
    return min((level, *(cap(signals) for cap in caps)))
