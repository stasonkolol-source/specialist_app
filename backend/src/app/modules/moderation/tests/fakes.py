"""Фейки портов moderation для тестов (ADR-0020 §11)."""

from dataclasses import dataclass, field
from datetime import timedelta

from app.modules.moderation.domain.rules import ContentRule, RuleSet


@dataclass
class StaticRuleSource:
    """RuleSource: словарь задаёт тест."""

    rules: list[ContentRule] = field(default_factory=list)

    async def current(self) -> RuleSet:
        return RuleSet(self.rules)


@dataclass
class MemoryVelocityCounter:
    """VelocityCounter в памяти; `available=False` — Valkey недоступен."""

    sets: dict[str, set[str]] = field(default_factory=dict)
    windows: dict[str, timedelta] = field(default_factory=dict)
    available: bool = True

    async def add(self, key: str, member: str, *, window: timedelta) -> int | None:
        if not self.available:
            return None
        self.windows.setdefault(key, window)
        members = self.sets.setdefault(key, set())
        members.add(member)
        return len(members)
