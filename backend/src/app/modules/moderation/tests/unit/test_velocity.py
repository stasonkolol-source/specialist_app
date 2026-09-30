"""Проверка правилами с velocity (DEVELOPMENT_PLAN 2.4): один текст от многих аккаунтов,
повтор автора, короткие тексты и недоступный счётчик."""

from datetime import timedelta
from uuid import UUID

import pytest

from app.modules.moderation.application.content_rules import ContentRulesChecker
from app.modules.moderation.application.dto import ContentCheck
from app.modules.moderation.domain.rules import (
    ContentRule,
    MatchSource,
    RuleAction,
    RuleCategory,
    RuleKind,
    RuleMatch,
)
from app.modules.moderation.domain.velocity import VELOCITY_LIMITS, fingerprint
from app.modules.moderation.tests.fakes import MemoryVelocityCounter, StaticRuleSource
from app.platform.ai.port import ContentKind
from app.platform.kernel.ids import UserId, new_id

pytestmark = pytest.mark.unit

FARM = "Здравствуйте! Выполню любую работу быстро и недорого, пишите в личные сообщения"
"""Длинный текст одной рассылки: у каждого аккаунта свой номер телефона."""


def check(
    author: UserId,
    kind: ContentKind = ContentKind.JOB,
    text: str = FARM,
    content_id: UUID | None = None,
) -> ContentCheck:
    return ContentCheck(author_id=author, kind=kind, content_id=content_id or new_id(), text=text)


def checker(counter: MemoryVelocityCounter, *rules: ContentRule) -> ContentRulesChecker:
    return ContentRulesChecker(StaticRuleSource(list(rules)), counter)


def velocity(matches: tuple[RuleMatch, ...]) -> list[str]:
    return [m.evidence for m in matches if m.source is MatchSource.VELOCITY]


async def test_same_text_from_three_accounts_is_a_farm() -> None:
    counter = MemoryVelocityCounter()
    rules = checker(counter)
    authors = [UserId(new_id()) for _ in range(3)]
    texts = [f"{FARM} +381 6{n} 123 456{n}" for n in range(3)]  # номера разные — текст один

    verdicts = [
        await rules.check(check(a, ContentKind.MESSAGE, t))
        for a, t in zip(authors, texts, strict=True)
    ]

    assert [v.action for v in verdicts[:2]] == [RuleAction.FLAG] * 2  # контакт — это flag детектора
    assert velocity(verdicts[1].matches) == []
    assert velocity(verdicts[2].matches) == ["same_text_accounts: 3"]
    assert RuleCategory.SPAM in verdicts[2].categories


async def test_author_repeating_a_job_is_counted_per_job_not_per_check() -> None:
    counter = MemoryVelocityCounter()
    rules = checker(counter)
    author = UserId(new_id())
    first_job = new_id()

    for _ in range(3):  # повторы проверки одной заявки (повтор задачи, правка)
        assert velocity((await rules.check(check(author, content_id=first_job))).matches) == []
    await rules.check(check(author))
    third = await rules.check(check(author))

    assert velocity(third.matches) == ["same_job_text: 3"]


async def test_template_responses_are_not_author_repeats() -> None:
    counter = MemoryVelocityCounter()
    rules = checker(counter)
    author = UserId(new_id())

    verdicts = [await rules.check(check(author, ContentKind.RESPONSE)) for _ in range(10)]

    assert all(velocity(v.matches) == [] for v in verdicts)
    assert [key.split(":")[0] for key in counter.sets] == ["same_text_accounts"]


async def test_short_texts_are_not_counted() -> None:
    counter = MemoryVelocityCounter()
    rules = checker(counter)

    for _ in range(5):
        await rules.check(check(UserId(new_id()), ContentKind.MESSAGE, "Здравствуйте, свободны?"))

    assert counter.sets == {}


async def test_unavailable_counter_skips_velocity_but_not_rules() -> None:
    counter = MemoryVelocityCounter(available=False)
    rule = ContentRule(
        pattern="любую работу",
        kind=RuleKind.WORD,
        action=RuleAction.FLAG,
        category=RuleCategory.SPAM,
    )
    rules = checker(counter, rule)

    verdicts = [await rules.check(check(UserId(new_id()))) for _ in range(4)]

    assert all([m.evidence for m in v.matches] == ["любую работу"] for v in verdicts)


async def test_windows_come_from_the_limits() -> None:
    counter = MemoryVelocityCounter()
    await checker(counter).check(check(UserId(new_id()), ContentKind.REVIEW))

    windows = {key.split(":")[0]: window for key, window in counter.windows.items()}
    assert windows == {
        "same_text_accounts": timedelta(days=1),
        "same_review_text": timedelta(days=30),
    }
    assert {limit.name for limit in VELOCITY_LIMITS} >= set(windows)


def test_fingerprint_ignores_contacts_case_and_disguises() -> None:
    base = fingerprint(f"{FARM} +381 64 123 4567")

    assert base is not None
    assert fingerprint(f"{FARM.upper()} +381 65 999 0000") == base
    assert fingerprint(FARM.replace("о", "0")) == base
    assert fingerprint("Добрый день, когда удобно?") is None
