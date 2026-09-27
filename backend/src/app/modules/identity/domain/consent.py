"""Согласия и акцепты (identity.consents, ARCHITECTURE §7.3, §13.4, ADR-0018).

Журнал: какой документ, какая версия, когда, с какой платформы. Повтор той же версии
новой записи не даёт; отзыв (v1) ставит `withdrawn_at`. В MVP одна галочка S02c
принимает правила площадки (в них же подтверждение 18+) и политику конфиденциальности;
остальные виды документов — задел v1.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final


class ConsentDocument(StrEnum):
    TERMS = "terms"
    """Правила площадки (backend/content/legal/terms/<версия>/<язык>.md)."""
    PRIVACY = "privacy"
    """Политика конфиденциальности (backend/content/legal/privacy/<версия>/<язык>.md)."""
    AGE_18 = "age_18"
    """Подтверждение 18+: часть правил, поэтому версия — версия правил."""
    PERFORMER_DECLARATION = "performer_declaration"
    ANALYTICS = "analytics"
    MARKETING = "marketing"
    PRECISE_LOCATION = "precise_location"
    AI_PROCESSING = "ai_processing"


ONE_TICK: Final = (ConsentDocument.TERMS, ConsentDocument.PRIVACY, ConsentDocument.AGE_18)
"""Что принимает одна галочка S02c и без чего нельзя создавать контент."""

MAX_VERSION = 64


@dataclass(frozen=True, slots=True, kw_only=True)
class Consent:
    """Действующее (не отозванное) согласие."""

    document: ConsentDocument
    version: str
    granted_at: datetime
