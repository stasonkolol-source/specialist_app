"""Velocity-правила: один и тот же текст много раз (ADR-0016 §3, research/06 §2.3).

Объём — сколько заявок, откликов и сообщений — ограничивают антиспам-лимиты ARCHITECTURE
§13.3: 429 ещё до записи. Velocity ловит другое — рассылку:
- один текст от нескольких аккаунтов за сутки — ферма или мошенническая рассылка (так
  работает Classiscam: одно первое сообщение многим продавцам);
- автор повторяет свой текст: одна заявка снова и снова, одно сообщение во многие диалоги.

Одинаковый текст — одинаковый отпечаток: скелет текста без контактов (номер телефона
мошенник меняет от аккаунта к аккаунту), sha256. Короткие тексты («Здравствуйте!») не
считаются: они одинаковые у всех. Отклики не считаются повтором автора: шаблон отклика —
нормальная работа специалиста.

Пороги — стартовые **[Допущение]**, их настраивают по очередям модерации.
"""

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from app.modules.moderation.domain.rules import MAX_TEXT, RuleAction, RuleCategory
from app.platform.ai.port import ContentKind
from app.platform.text.contact_masking import mask_contacts
from app.platform.text.normalize import skeleton

MIN_FINGERPRINT_CHARS = 30
"""Скелет короче — текст не считаем: приветствия и «спасибо» одинаковы у всех."""


class VelocityScope(StrEnum):
    ACCOUNTS = "accounts"
    """Разные аккаунты с одним текстом."""
    AUTHOR = "author"
    """Разные единицы контента одного автора с одним текстом."""


@dataclass(frozen=True, slots=True, kw_only=True)
class VelocityLimit:
    name: str
    scope: VelocityScope
    kinds: frozenset[ContentKind]
    threshold: int
    """Срабатывает, когда различных аккаунтов (или единиц контента) стало столько."""
    window: timedelta
    action: RuleAction = RuleAction.FLAG
    category: RuleCategory = RuleCategory.SPAM


VELOCITY_LIMITS: tuple[VelocityLimit, ...] = (
    VelocityLimit(
        name="same_text_accounts",
        scope=VelocityScope.ACCOUNTS,
        kinds=frozenset(ContentKind),
        threshold=3,
        window=timedelta(days=1),
    ),
    VelocityLimit(
        name="same_job_text",
        scope=VelocityScope.AUTHOR,
        kinds=frozenset({ContentKind.JOB}),
        threshold=3,
        window=timedelta(days=7),
    ),
    VelocityLimit(
        name="same_message_text",
        scope=VelocityScope.AUTHOR,
        kinds=frozenset({ContentKind.MESSAGE}),
        threshold=5,
        window=timedelta(hours=1),
    ),
    VelocityLimit(
        name="same_review_text",
        scope=VelocityScope.AUTHOR,
        kinds=frozenset({ContentKind.REVIEW}),
        threshold=2,
        window=timedelta(days=30),
    ),
)


def fingerprint(text: str) -> str | None:
    """Отпечаток текста для velocity; None — текст слишком короткий, чтобы сравнивать."""
    words = skeleton(mask_contacts(text[:MAX_TEXT]))
    if len(words) < MIN_FINGERPRINT_CHARS:
        return None
    return hashlib.sha256(words.encode()).hexdigest()[:32]
