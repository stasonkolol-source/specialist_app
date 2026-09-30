"""Импорт словаря контент-правил из сидов (DEVELOPMENT_PLAN 2.4, `cli seed`)."""

from dataclasses import dataclass

from app.modules.moderation.application.dto import ImportRulesResult
from app.modules.moderation.application.ports import RuleWriter
from app.modules.moderation.domain.rules import ContentRule
from app.platform.db.port import UnitOfWork


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportContentRulesCommand:
    rules: tuple[ContentRule, ...]
    """Все правила файла сида, в том числе выключенные (`active: false`)."""


class ImportContentRules:
    def __init__(self, uow: UnitOfWork, writer: RuleWriter) -> None:
        self._uow, self._writer = uow, writer

    async def __call__(self, cmd: ImportContentRulesCommand) -> ImportRulesResult:
        async with self._uow:
            return await self._writer.import_seed(cmd.rules)
