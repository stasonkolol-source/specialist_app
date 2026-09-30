"""Velocity-правила (DEVELOPMENT_PLAN 2.4): отпечаток текста и пороги. Сама проверка со
счётчиками в Valkey — tests/integration/test_content_check.py."""

import pytest

from app.modules.moderation.domain.velocity import (
    MIN_FINGERPRINT_CHARS,
    VELOCITY_LIMITS,
    VelocityScope,
    fingerprint,
)
from app.platform.ai.port import ContentKind

pytestmark = pytest.mark.unit

FARM = "Здравствуйте! Выполню любую работу быстро и недорого, пишите в личные сообщения"


def test_fingerprint_ignores_contacts_case_and_disguises() -> None:
    base = fingerprint(f"{FARM} +381 64 123 4567")

    assert base is not None
    assert fingerprint(f"{FARM.upper()} +381 65 999 0000") == base  # номер у фермы свой
    assert fingerprint(FARM.replace("о", "0")) == base
    assert fingerprint(f"{FARM} bit.ly/x") == fingerprint(f"{FARM} tinyurl.com/y")  # ссылки тоже


def test_short_texts_have_no_fingerprint() -> None:
    assert fingerprint("Добрый день, когда удобно?") is None
    assert fingerprint("Нужен электрик завтра утром, заменить три розетки") is not None
    assert fingerprint("о" * MIN_FINGERPRINT_CHARS * 2) is None  # повторы — одна буква


def test_template_responses_are_not_author_repeats() -> None:
    author_limits = [limit for limit in VELOCITY_LIMITS if limit.scope is VelocityScope.AUTHOR]

    assert all(ContentKind.RESPONSE not in limit.kinds for limit in author_limits)
    assert len({limit.name for limit in VELOCITY_LIMITS}) == len(VELOCITY_LIMITS)
