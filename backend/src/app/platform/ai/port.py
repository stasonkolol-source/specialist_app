"""Порты AI-проверок контента (ADR-0016 §3, ARCHITECTURE §14.1, DEVELOPMENT_PLAN 2.4).

- `Moderation` — универсальный классификатор текста и изображений (OpenAI omni-moderation).
- `PolicyClassifier` — политика маркетплейса (Claude Haiku 4.5): метки ADR-0016, уверенность
  и объяснение для модератора.
- `SecondaryImage` — второй проверяющий изображений, на которых сработал первый (Q20: пока
  без него — такие изображения идут в ручную очередь).

Проверка, которая не состоялась (нет ключа, таймаут, сбой, открыт предохранитель, отказ
модели), — не исключение и не «чисто», а отдельный ответ `Unavailable`: модерация отправит
контент в ручную очередь, а не опубликует его без проверки (ADR-0016). Это отдельный тип, а не
флаг: у `Unavailable` нет метки и `flagged`, поэтому mypy не даст прочитать их, не разобрав
случай «недоступно». В AI уходит минимум — текст без контактов (contact_masking).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol


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


class UnavailableReason(StrEnum):
    NO_KEY = "no_key"
    """Ключа нет: stage и прод без K25/K26."""
    NOT_CONFIGURED = "not_configured"
    """Проверки нет по решению (Q20: второй проверяющий изображений)."""
    BREAKER_OPEN = "breaker_open"
    PROVIDER_ERROR = "provider_error"
    """Сеть, таймаут, 429, 5xx, 401, неожиданный ответ."""
    REJECTED_INPUT = "rejected_input"
    """Провайдер не принял именно этот запрос (400, 413, 422): изображение не скачалось и т. п."""
    NO_VERDICT = "no_verdict"
    """Ответ есть, вердикта нет: отказ модели, ответ не по схеме."""


@dataclass(frozen=True, slots=True)
class Unavailable:
    """Проверка не состоялась — контент в ручную очередь (ADR-0016)."""

    reason: UnavailableReason


@dataclass(frozen=True, slots=True, kw_only=True)
class ModerationResult:
    flagged: bool
    scores: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))
    """Категория классификатора → уверенность 0–1."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PolicyVerdict:
    label: PolicyLabel
    confidence: float
    """0–1: насколько классификатор уверен в метке."""
    explanation: str
    """Коротко, по-русски — для модератора (пользователю не показывается)."""


class Moderation(Protocol):
    async def check_text(self, text: str) -> ModerationResult | Unavailable: ...

    async def check_image(self, url: str) -> ModerationResult | Unavailable:
        """Изображение: `data:` URL варианта `md` (prompt.image_data_url, 6.7) — или адрес,
        который провайдер может скачать."""
        ...


class PolicyClassifier(Protocol):
    async def classify(self, text: str, *, kind: ContentKind) -> PolicyVerdict | Unavailable: ...


class SecondaryImage(Protocol):
    async def check(self, url: str) -> ModerationResult | Unavailable: ...
