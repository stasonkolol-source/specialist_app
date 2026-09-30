"""Словарь модерации из сидов в PostgreSQL (DEVELOPMENT_PLAN 2.4): повторный импорт ничего не
меняет, а правила, прочитанные из БД, проходят набор примеров так же, как файл."""

from pathlib import Path
from typing import Any

import procrastinate
import pytest
import yaml
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from app.entrypoints.seeds import SEEDS_DIR, load_content_rules_seed
from app.modules.moderation.application.dto import ImportRulesResult
from app.modules.moderation.application.use_cases.import_content_rules import (
    ImportContentRules,
    ImportContentRulesCommand,
)
from app.modules.moderation.infrastructure.rules import CachedRuleSource, SqlRuleWriter
from tests.plugins.database import make_uow

pytestmark = pytest.mark.integration


async def _import(db_session: AsyncSession, app: procrastinate.App) -> ImportRulesResult:
    uow = make_uow(db_session, app)
    use_case = ImportContentRules(uow, SqlRuleWriter(db_session, uow))
    return await use_case(ImportContentRulesCommand(rules=tuple(load_content_rules_seed())))


def _examples() -> list[dict[str, Any]]:
    path = Path(SEEDS_DIR) / "moderation" / "rule_examples.yaml"
    examples: list[dict[str, Any]] = yaml.safe_load(path.read_text(encoding="utf-8"))["examples"]
    return examples


async def test_second_import_changes_nothing_and_db_rules_pass_the_examples(
    db_session: AsyncSession,
    db_connection: AsyncConnection,
    procrastinate_app: procrastinate.App,
) -> None:
    total = len(load_content_rules_seed())

    first = await _import(db_session, procrastinate_app)
    second = await _import(db_session, procrastinate_app)

    assert (first.created, first.updated, first.unchanged) == (total, 0, 0)
    assert (second.created, second.updated, second.unchanged, second.deactivated) == (
        0,
        0,
        total,
        0,
    )
    maker = async_sessionmaker(bind=db_connection, join_transaction_mode="create_savepoint")
    rules = await CachedRuleSource(maker).current()
    assert len(rules) == total
    assert rules.rejected == ()
    for example in _examples():
        verdict = rules.check(example["text"])
        action = verdict.action.value if verdict.action else "pass"
        categories = sorted(c.value for c in verdict.categories)
        assert (action, categories) == (example["action"], sorted(example.get("categories", []))), (
            example["text"]
        )
