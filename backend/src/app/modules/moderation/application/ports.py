"""Порты модуля moderation (ADR-0020 §3, §5)."""

from collections.abc import Sequence
from datetime import timedelta
from typing import Protocol

from app.modules.moderation.application.dto import ImportRulesResult
from app.modules.moderation.domain.rules import ContentRule, RuleSet


class RuleSource(Protocol):
    async def current(self) -> RuleSet:
        """Действующие правила: снимок из БД, обновляется раз в TTL. БД недоступна — прошлый
        снимок (до первой загрузки — пустой: работают только детекторы platform/text)."""
        ...


class RuleWriter(Protocol):
    async def import_seed(self, rules: Sequence[ContentRule]) -> ImportRulesResult:
        """Правила сида — в БД идемпотентно (infrastructure/rules.py). Нужен активный UoW."""
        ...


class VelocityCounter(Protocol):
    async def add(self, key: str, member: str, *, window: timedelta) -> int | None:
        """Добавить member в множество key и вернуть, сколько в нём различных. Множество
        живёт `window` с первого добавления. None — счётчик недоступен: правило пропускается
        (fail open — антиспам не останавливает публикацию)."""
        ...
