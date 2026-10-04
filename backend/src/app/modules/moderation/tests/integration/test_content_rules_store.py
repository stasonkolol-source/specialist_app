"""Словарь контент-правил в PostgreSQL (DEVELOPMENT_PLAN 2.4): импорт сида идемпотентен,
строки админки он не трогает (и поправленную в админке строку сида узнаёт по `seed_key`); снимок
для проверки читает только действующие правила и переживает сбой БД."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from typing import Any, cast

import procrastinate
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from structlog.testing import capture_logs
from tests.plugins.database import make_uow

from app.modules.moderation.application.dto import ImportRulesResult
from app.modules.moderation.application.use_cases.import_content_rules import (
    ImportContentRules,
    ImportContentRulesCommand,
)
from app.modules.moderation.domain.rules import (
    ContentRule,
    RuleAction,
    RuleCategory,
    RuleKind,
    RuleLanguage,
)
from app.modules.moderation.infrastructure.rules import CachedRuleSource, SqlRuleWriter

pytestmark = pytest.mark.integration

KOKAIN = ContentRule(
    pattern="kokain*",
    kind=RuleKind.WORD,
    action=RuleAction.FLAG,
    category=RuleCategory.DRUGS,
    lang=RuleLanguage.SR,
)
KLADMEN = ContentRule(
    pattern="кладмен*", kind=RuleKind.WORD, action=RuleAction.BLOCK, category=RuleCategory.DRUGS
)
SHORTENER = ContentRule(
    pattern="bit.ly", kind=RuleKind.DOMAIN, action=RuleAction.FLAG, category=RuleCategory.SPAM
)


async def run_import(
    session: AsyncSession, app: procrastinate.App, *rules: ContentRule
) -> ImportRulesResult:
    uow = make_uow(session, app)
    use_case = ImportContentRules(uow, SqlRuleWriter(session, uow))
    return await use_case(ImportContentRulesCommand(rules=rules))


async def stored(session: AsyncSession) -> dict[str, tuple[Any, ...]]:
    rows = await session.execute(
        text("SELECT pattern, action, is_active, origin FROM moderation.content_rules")
    )
    return {row.pattern: (row.action, row.is_active, row.origin) for row in rows}


def counts(result: ImportRulesResult) -> tuple[int, int, int, int, int]:
    return (result.created, result.updated, result.unchanged, result.deactivated, result.skipped)


async def test_seed_import_is_idempotent_and_owns_only_its_rows(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    await db_session.execute(
        text(
            "INSERT INTO moderation.content_rules (pattern, kind, action, category)"
            " VALUES ('bit.ly', 'domain', 'block', 'scam')"
        )
    )  # правило админки: origin по умолчанию — admin
    await db_session.commit()

    first = await run_import(db_session, procrastinate_app, KOKAIN, KLADMEN, SHORTENER)
    again = await run_import(db_session, procrastinate_app, KOKAIN, KLADMEN, SHORTENER)
    stricter = replace(KOKAIN, action=RuleAction.BLOCK)
    edited = await run_import(db_session, procrastinate_app, stricter, SHORTENER)

    assert counts(first) == (2, 0, 0, 0, 1)
    assert counts(again) == (0, 0, 2, 0, 1)
    assert counts(edited) == (0, 1, 0, 1, 1)
    assert await stored(db_session) == {
        "kokain*": ("block", True, "seed"),
        "кладмен*": ("block", False, "seed"),  # пропал из файла — выключен, строка осталась
        "bit.ly": ("block", True, "admin"),  # админку сид не трогает
    }
    back = await run_import(db_session, procrastinate_app, stricter, KLADMEN, SHORTENER)
    assert counts(back) == (0, 1, 1, 0, 1)  # вернулся в файл — снова включён


async def test_seed_import_keeps_a_rule_edited_in_admin_and_does_not_resurrect_it(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    """Строку сида узнают по `seed_key`: шаблон, поправленный в админке, не возвращает исходное
    правило; строка сида без ключа (до moderation_0009) получает его, а не дубль."""
    await run_import(db_session, procrastinate_app, KOKAIN, KLADMEN)
    await db_session.execute(
        text(
            "UPDATE moderation.content_rules SET pattern = 'kokaini*', origin = 'admin'"
            " WHERE pattern = 'kokain*'"
        )
    )  # правка в админке: шаблон и владелец
    await db_session.execute(
        text(
            "INSERT INTO moderation.content_rules (pattern, kind, action, category, origin)"
            " VALUES ('bit.ly', 'domain', 'flag', 'spam', 'seed')"
        )
    )  # строка сида без ключа
    await db_session.commit()

    again = await run_import(db_session, procrastinate_app, KOKAIN, KLADMEN, SHORTENER)
    stricter = await run_import(
        db_session, procrastinate_app, replace(KOKAIN, action=RuleAction.BLOCK), KLADMEN, SHORTENER
    )

    assert counts(again) == (0, 0, 2, 0, 1)
    assert counts(stricter) == (0, 0, 2, 0, 1)  # правку файла строка админки не принимает
    assert await stored(db_session) == {
        "kokaini*": ("flag", True, "admin"),  # исходного «kokain*» нет — не воскрес
        "кладмен*": ("block", True, "seed"),
        "bit.ly": ("flag", True, "seed"),
    }
    keys = await db_session.execute(
        text("SELECT pattern, seed_key FROM moderation.content_rules ORDER BY pattern")
    )
    assert {row.pattern: row.seed_key for row in keys} == {
        "bit.ly": "domain:bit.ly",
        "kokaini*": "word:kokain*",  # ключ — правило сида, как оно записано в файле
        "кладмен*": "word:кладмен*",
    }


def source(connection: AsyncConnection, ttl: timedelta, clock: list[float]) -> CachedRuleSource:
    maker = async_sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    return CachedRuleSource(maker, ttl=ttl, monotonic=lambda: clock[0])


async def test_snapshot_has_active_rules_and_refreshes_after_ttl(
    db_session: AsyncSession,
    db_connection: AsyncConnection,
    procrastinate_app: procrastinate.App,
) -> None:
    await run_import(db_session, procrastinate_app, KOKAIN, SHORTENER)
    await db_session.execute(
        text("UPDATE moderation.content_rules SET is_active = false WHERE pattern = 'bit.ly'")
    )
    await db_session.commit()
    clock = [100.0]
    rules = source(db_connection, timedelta(seconds=60), clock)

    snapshot = await rules.current()
    assert [m.evidence for m in snapshot.check("Kokain na bit.ly/x").matches] == [
        "kokain*",
        "link",  # детектор контактов работает всегда
    ]
    assert snapshot.check("Kokain").matches[0].rule_id is not None

    await run_import(db_session, procrastinate_app, KOKAIN, KLADMEN, SHORTENER)
    assert await rules.current() is snapshot  # в пределах TTL — тот же снимок
    clock[0] += 61
    fresh = await rules.current()
    assert [m.evidence for m in fresh.check("кладмен, bit.ly/x").matches] == [
        "кладмен*",
        "bit.ly",
        "link",
    ]


async def test_broken_rule_is_skipped_and_reported_once(
    db_session: AsyncSession, db_connection: AsyncConnection
) -> None:
    await db_session.execute(
        text(
            "INSERT INTO moderation.content_rules (pattern, kind, action, category, origin)"
            " VALUES ('(oops', 'regex', 'flag', 'spam', 'seed'),"
            " ('heroin*', 'word', 'flag', 'drugs', 'seed')"
        )
    )
    await db_session.commit()
    clock = [0.0]
    rules = source(db_connection, timedelta(seconds=1), clock)

    with capture_logs() as logs:
        first = await rules.current()
        clock[0] += 2
        await rules.current()

    assert [m.evidence for m in first.check("heroin").matches] == ["heroin*"]
    assert [entry["event"] for entry in logs] == ["content_rule_invalid"]


class _Down:
    """async_sessionmaker, у которого БД недоступна."""

    def __call__(self) -> _Down:
        return self

    async def __aenter__(self) -> AsyncSession:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    async def __aexit__(self, *exc: object) -> None:
        return None


async def test_database_outage_keeps_the_last_snapshot(
    db_session: AsyncSession, db_connection: AsyncConnection, procrastinate_app: procrastinate.App
) -> None:
    await run_import(db_session, procrastinate_app, KOKAIN)
    clock = [0.0]
    rules = source(db_connection, timedelta(seconds=1), clock)
    snapshot = await rules.current()
    rules._maker = cast(async_sessionmaker[AsyncSession], _Down())  # сбой после загрузки

    clock[0] += 2
    with capture_logs() as logs:
        after_outage = await rules.current()

    assert after_outage is snapshot
    assert [entry["event"] for entry in logs] == ["content_rules_unavailable"]


async def test_dictionary_that_fails_to_build_keeps_the_last_snapshot(
    db_session: AsyncSession,
    db_connection: AsyncConnection,
    procrastinate_app: procrastinate.App,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await run_import(db_session, procrastinate_app, KOKAIN)
    clock = [0.0]
    rules = source(db_connection, timedelta(seconds=1), clock)
    snapshot = await rules.current()

    def broken(*_: object) -> None:
        raise RuntimeError("unexpected")

    monkeypatch.setattr("app.modules.moderation.infrastructure.rules.RuleSet", broken)
    clock[0] += 2
    with capture_logs() as logs:
        after = await rules.current()

    assert after is snapshot
    assert [entry["event"] for entry in logs] == ["content_rules_build_failed"]


class _Blocked:
    """async_sessionmaker, у которого БД отвечает только после `gate` (или никогда)."""

    def __init__(self, gate: asyncio.Event) -> None:
        self._gate = gate

    def __call__(self) -> _Blocked:
        return self

    async def __aenter__(self) -> AsyncSession:
        await self._gate.wait()
        raise OperationalError("SELECT 1", {}, Exception("too late"))

    async def __aexit__(self, *exc: object) -> None:
        return None


async def test_readers_get_the_last_snapshot_while_it_refreshes(
    db_session: AsyncSession, db_connection: AsyncConnection, procrastinate_app: procrastinate.App
) -> None:
    await run_import(db_session, procrastinate_app, KOKAIN)
    clock = [0.0]
    rules = source(db_connection, timedelta(seconds=1), clock)
    snapshot = await rules.current()
    gate = asyncio.Event()
    rules._maker = cast(async_sessionmaker[AsyncSession], _Blocked(gate))  # БД задумалась

    clock[0] += 2
    refreshing = asyncio.create_task(rules.current())
    await asyncio.sleep(0)  # обновление взяло блокировку и ждёт БД

    async with asyncio.timeout(1):
        assert await rules.current() is snapshot  # без ожидания
    gate.set()
    assert await refreshing is snapshot


async def test_slow_database_keeps_the_last_snapshot(
    db_session: AsyncSession,
    db_connection: AsyncConnection,
    procrastinate_app: procrastinate.App,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await run_import(db_session, procrastinate_app, KOKAIN)
    clock = [0.0]
    rules = source(db_connection, timedelta(seconds=1), clock)
    snapshot = await rules.current()
    monkeypatch.setattr(
        "app.modules.moderation.infrastructure.rules.REFRESH_TIMEOUT", timedelta(milliseconds=50)
    )
    rules._maker = cast(async_sessionmaker[AsyncSession], _Blocked(asyncio.Event()))

    clock[0] += 2
    with capture_logs() as logs:
        async with asyncio.timeout(1):
            assert await rules.current() is snapshot

    assert [(entry["event"], entry["error"]) for entry in logs] == [
        ("content_rules_unavailable", "TimeoutError")
    ]


async def test_an_empty_dictionary_is_reported(db_connection: AsyncConnection) -> None:
    rules = source(db_connection, timedelta(seconds=60), [0.0])

    with capture_logs() as logs:
        await rules.current()

    assert [entry["event"] for entry in logs] == ["content_rules_empty"]


async def test_admin_regex_rules_are_stored_and_searched_by_re2(
    db_session: AsyncSession, db_connection: AsyncConnection
) -> None:
    # moderation_0007 снял CHECK regex_from_seed: RE2 линеен при любом шаблоне, поэтому
    # регулярку заводит и админка (её проверяет та же compile_rule, что сид в seeds-validate)
    pattern = r"\bkupim\w* (?:dolar|evr)\w*"
    await db_session.execute(
        text(
            "INSERT INTO moderation.content_rules (pattern, kind, action, category)"
            " VALUES (:pattern, 'regex', 'flag', 'spam')"
        ),
        {"pattern": pattern},
    )  # origin по умолчанию — admin
    await db_session.commit()

    snapshot = await source(db_connection, timedelta(seconds=60), [0.0]).current()

    assert [m.evidence for m in snapshot.check("Kupim EVRE po dobrom kursu").matches] == [pattern]
    assert snapshot.rejected == ()
