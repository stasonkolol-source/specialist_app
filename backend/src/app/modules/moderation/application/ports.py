"""Порты модуля moderation (ADR-0020 §3, §5)."""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.modules.moderation.application.dto import ImportRulesResult, QueueSla
from app.modules.moderation.domain.cases import Case, EntityType
from app.modules.moderation.domain.risk import RiskSignal
from app.modules.moderation.domain.rules import ContentRule, RuleSet
from app.modules.moderation.domain.sanctions import Sanction
from app.platform.kernel.ids import CaseId, UserId


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


class CaseRepository(Protocol):
    async def get_for_update(self, case_id: CaseId) -> Case:
        """Кейс под блокировкой строки. CaseNotFoundError — нет такого."""
        ...

    async def open_for_entity(self, entity_type: EntityType, entity_id: UUID) -> Case | None:
        """Открытый кейс объекта под блокировкой строки."""
        ...

    async def add(self, case: Case) -> None:
        """CaseAlreadyOpenError — параллельный запрос только что открыл кейс того же объекта."""
        ...

    async def save(self, case: Case) -> None: ...


class SanctionRepository(Protocol):
    async def counted(self, user_id: UserId, now: datetime) -> int:
        """Несгоревшие и неотменённые предупреждения и страйки 1–2 пользователя."""
        ...

    async def add(self, sanction: Sanction) -> None: ...


class RiskSignals(Protocol):
    async def add(self, signals: Sequence[RiskSignal]) -> int:
        """Записать сигналы; с уже записанным `dedupe_key` — пропустить. Сколько новых."""
        ...


class CaseStats(Protocol):
    async def sla(self, *, since: datetime, until: datetime, now: datetime) -> list[QueueSla]:
        """SLA по очередям: решённые за [since, until) и сколько из них в срок; открытые и
        просроченные к `now`."""
        ...


class RateLimitOverflows(Protocol):
    async def by_user(self, day: date) -> Mapping[UserId, Mapping[str, int]]:
        """Превышения антиспам-лимитов пользователями за сутки (UTC): лимит → сколько 429
        (platform/ratelimit.py, шаг 0.13b). Счётчики недоступны — пусто."""
        ...


class ModerationPolicy(Protocol):
    async def version(self) -> str:
        """Действующая версия политики модерации — в каждое решение (ADR-0016 §4)."""
        ...
