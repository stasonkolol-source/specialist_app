"""Проверка правилами — первый шаг конвейера (DEVELOPMENT_PLAN 2.4): словарь из PostgreSQL,
детекторы platform/text и velocity на настоящем Valkey. Один текст от трёх аккаунтов — ферма;
повтор автора считается по единицам контента, а не по проверкам; короткие тексты не
считаются; недоступный Valkey не мешает правилам."""

from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID

import procrastinate
import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from structlog.testing import capture_logs
from tests.plugins.database import make_uow

from app.modules.moderation.application.content_rules import ContentRulesChecker
from app.modules.moderation.application.dto import ContentCheck
from app.modules.moderation.application.use_cases.import_content_rules import (
    ImportContentRules,
    ImportContentRulesCommand,
)
from app.modules.moderation.domain.rules import (
    ContentRule,
    MatchSource,
    RuleAction,
    RuleCategory,
    RuleKind,
    RuleMatch,
    RulesVerdict,
)
from app.modules.moderation.infrastructure.rules import CachedRuleSource, SqlRuleWriter
from app.modules.moderation.infrastructure.velocity import ValkeyVelocityCounter
from app.platform.ai.port import ContentKind
from app.platform.kernel.ids import UserId, new_id

pytestmark = pytest.mark.integration

FARM = "Здравствуйте! Выполню любую работу быстро и недорого, пишите в личные сообщения"
"""Длинный текст одной рассылки: у каждого аккаунта свой номер телефона."""
ANY_JOB = ContentRule(
    pattern="любую работу", kind=RuleKind.WORD, action=RuleAction.FLAG, category=RuleCategory.SPAM
)


@pytest.fixture
async def valkey(valkey_url: str) -> AsyncIterator[Redis]:
    client = Redis.from_url(valkey_url)
    yield client
    await client.aclose()


@pytest.fixture
def prefix() -> str:
    return f"test:{new_id().hex}:"  # свои счётчики на тест


def checker(connection: AsyncConnection, valkey: Redis, prefix: str) -> ContentRulesChecker:
    maker = async_sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    return ContentRulesChecker(
        CachedRuleSource(maker), ValkeyVelocityCounter(valkey, prefix=prefix)
    )


def check(
    author: UserId,
    kind: ContentKind = ContentKind.JOB,
    text: str = FARM,
    content_id: UUID | None = None,
) -> ContentCheck:
    return ContentCheck(author_id=author, kind=kind, content_id=content_id or new_id(), text=text)


def velocity(verdict: RulesVerdict) -> list[str]:
    return [m.evidence for m in verdict.matches if m.source is MatchSource.VELOCITY]


def author() -> UserId:
    return UserId(new_id())


async def test_same_text_from_three_accounts_is_a_farm(
    db_connection: AsyncConnection, valkey: Redis, prefix: str
) -> None:
    rules = checker(db_connection, valkey, prefix)
    texts = [f"{FARM} +381 6{n} 123 456{n}" for n in range(3)]  # номера разные — текст один

    verdicts = [await rules.check(check(author(), ContentKind.MESSAGE, t)) for t in texts]

    assert [velocity(v) for v in verdicts] == [[], [], ["same_text_accounts: 3"]]
    assert RuleCategory.SPAM in verdicts[2].categories
    assert RuleCategory.CONTACTS in verdicts[0].categories  # детектор работает без словаря


async def test_author_repeating_a_job_is_counted_per_job_not_per_check(
    db_connection: AsyncConnection, valkey: Redis, prefix: str
) -> None:
    rules = checker(db_connection, valkey, prefix)
    someone, first_job = author(), new_id()

    for _ in range(3):  # повторы проверки одной заявки (повтор задачи, правка)
        assert velocity(await rules.check(check(someone, content_id=first_job))) == []
    await rules.check(check(someone))
    third = await rules.check(check(someone))

    assert velocity(third) == ["same_job_text: 3"]


async def test_template_responses_are_not_author_repeats(
    db_connection: AsyncConnection, valkey: Redis, prefix: str
) -> None:
    rules = checker(db_connection, valkey, prefix)
    someone = author()

    verdicts = [await rules.check(check(someone, ContentKind.RESPONSE)) for _ in range(10)]

    assert all(velocity(v) == [] for v in verdicts)


async def test_short_texts_are_not_counted(
    db_connection: AsyncConnection, valkey: Redis, prefix: str
) -> None:
    rules = checker(db_connection, valkey, prefix)

    for _ in range(5):
        await rules.check(check(author(), ContentKind.MESSAGE, "Здравствуйте, свободны?"))

    assert [key async for key in valkey.scan_iter(f"{prefix}*")] == []


async def test_counter_window_comes_from_the_limit(
    db_connection: AsyncConnection, valkey: Redis, prefix: str
) -> None:
    await checker(db_connection, valkey, prefix).check(check(author(), ContentKind.REVIEW))

    ttls = {
        key.decode().removeprefix(prefix).split(":")[0]: await valkey.ttl(key)
        async for key in valkey.scan_iter(f"{prefix}*")
    }
    assert set(ttls) == {"same_text_accounts", "same_review_text"}
    assert timedelta(hours=23) < timedelta(seconds=ttls["same_text_accounts"]) <= timedelta(days=1)
    assert timedelta(days=29) < timedelta(seconds=ttls["same_review_text"]) <= timedelta(days=30)


async def test_dictionary_rules_apply_and_survive_valkey_outage(
    db_session: AsyncSession,
    db_connection: AsyncConnection,
    procrastinate_app: procrastinate.App,
) -> None:
    uow = make_uow(db_session, procrastinate_app)
    await ImportContentRules(uow, SqlRuleWriter(db_session, uow))(
        ImportContentRulesCommand(rules=(ANY_JOB,))
    )
    down = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    rules = checker(db_connection, down, "test:")
    try:
        with capture_logs() as logs:
            verdicts = [await rules.check(check(author())) for _ in range(4)]
    finally:
        await down.aclose()

    [match] = verdicts[3].matches
    assert match == RuleMatch(
        source=MatchSource.RULE,
        category=RuleCategory.SPAM,
        action=RuleAction.FLAG,
        evidence="любую работу",
        rule_id=match.rule_id,
    )
    assert match.rule_id is not None
    assert {entry["event"] for entry in logs} == {"velocity_unavailable"}
