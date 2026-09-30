"""Порты AI-проверок контента (ADR-0016 §3, ARCHITECTURE §14.1, DEVELOPMENT_PLAN 2.4).

- `Moderation` — универсальный классификатор текста и изображений (OpenAI omni-moderation).
- `PolicyClassifier` — политика маркетплейса (Claude Haiku 4.5): метки ADR-0016, уверенность
  и объяснение для модератора.
- `SecondaryImage` — второй проверяющий изображений, на которых сработал первый (Q20: пока
  без него — такие изображения идут в ручную очередь).

Недоступная проверка (нет ключа, таймаут, сбой, открыт предохранитель) — не исключение, а
вердикт `available=False`: модерация отправит контент в ручную очередь, а не опубликует
его без проверки (ADR-0016). В AI уходит минимум — текст без контактов (contact_masking).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, Self


class ContentKind(StrEnum):
    """Что проверяем: от этого зависят уместные метки (заявка может быть «не заявкой»)."""

    JOB = "job"
    RESPONSE = "response"
    MESSAGE = "message"
    PROFILE = "profile"
    REVIEW = "review"


class PolicyLabel(StrEnum):
    """Метки политики (ADR-0016 §3)."""

    PREPAYMENT_SCAM = "prepayment_scam"
    OFF_PLATFORM_PAYMENT = "off_platform_payment"
    MULE_RECRUITMENT = "mule_recruitment"
    DRUG_COURIER = "drug_courier"
    SEXUAL_SERVICES = "sexual_services"
    WEAPONS = "weapons"
    CONTACT_LEAK = "contact_leak"
    SPAM_AD = "spam_ad"
    NOT_A_SERVICE_REQUEST = "not_a_service_request"
    VACANCY = "vacancy"
    OK = "ok"


@dataclass(frozen=True, slots=True, kw_only=True)
class ModerationResult:
    flagged: bool
    scores: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))
    """Категория классификатора → уверенность 0–1."""
    available: bool = True
    """False — проверка не состоялась: контент — в ручную очередь."""

    @classmethod
    def unavailable(cls) -> Self:
        return cls(flagged=False, available=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class PolicyVerdict:
    label: PolicyLabel
    confidence: float
    """0–1: насколько классификатор уверен в метке."""
    explanation: str
    """Коротко, по-русски — для модератора (пользователю не показывается)."""
    available: bool = True

    @classmethod
    def unavailable(cls) -> Self:
        return cls(label=PolicyLabel.OK, confidence=0.0, explanation="", available=False)


class Moderation(Protocol):
    async def check_text(self, text: str) -> ModerationResult: ...

    async def check_image(self, url: str) -> ModerationResult:
        """Изображение по адресу (presigned GET варианта `md`)."""
        ...


class PolicyClassifier(Protocol):
    async def classify(self, text: str, *, kind: ContentKind) -> PolicyVerdict: ...


class SecondaryImage(Protocol):
    async def check(self, url: str) -> ModerationResult: ...
