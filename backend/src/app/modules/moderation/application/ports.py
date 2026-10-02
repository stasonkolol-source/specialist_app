"""Порты модуля moderation (ADR-0020 §3, §5)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final, Protocol
from uuid import UUID

from app.modules.moderation.application.dto import ImportRulesResult, OpenCaseView, QueueSla
from app.modules.moderation.domain.cases import Case, EntityType
from app.modules.moderation.domain.pipeline import Route
from app.modules.moderation.domain.risk import RiskSignal
from app.modules.moderation.domain.rules import ContentRule, RuleSet
from app.modules.moderation.domain.sanctions import Sanction
from app.platform.ai.port import ContentKind
from app.platform.contracts.events.identity import UserRegistered
from app.platform.contracts.events.moderation import ModerationRequested
from app.platform.kernel.ids import CaseId, MediaId, UserId
from app.platform.queue.port import TaskRef


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


@dataclass(frozen=True, slots=True, kw_only=True)
class TargetContent:
    """Что проверять у объекта: текст целиком (заголовок, описание, …) и его файлы."""

    author_id: UserId
    kind: ContentKind
    text: str
    media_ids: tuple[MediaId, ...] = ()
    version: int | None = None
    """Версия, которую проверяли: публикация устаревшей версии — ничего не делает."""
    always_review: bool = False
    """Профили и портфолио новых — всегда через человека (§14.1)."""
    risk_level: int = 0
    """Риск категории (1.3b): `≥ 1` — в очередь (§14.1)."""
    visible: bool = False
    """Объект уже виден (сообщение чата, 6.3a): признак нарушения скрывает его до решения
    модератора, одобрение возвращает."""


class ModerationTarget(Protocol):
    """Адаптер цели (moderation/infrastructure/targets): фасад модуля-владельца объекта.

    Контентные модули ниже moderation по DAG и о нём не знают: модерация сама читает объект
    и сама публикует или скрывает его через их фасады, в своей транзакции.
    """

    async def content(self, entity_id: UUID) -> TargetContent | None:
        """Что проверять; None — объекта нет или он уже не ждёт проверки."""
        ...

    async def publish(self, entity_id: UUID, *, version: int | None = None) -> None:
        """Проверка пройдена: «на проверке» → «опубликован»; в другом статусе или другой
        версии — ничего (автор успел изменить или снять объект)."""
        ...

    async def hide(self, entity_id: UUID, *, reason_code: str) -> None:
        """Нарушение: скрыть объект модерацией."""
        ...


class ModerationTargets(Protocol):
    def get(self, entity_type: EntityType) -> ModerationTarget | None:
        """Адаптер цели; None — модуль-владелец ещё не подключён к конвейеру."""
        ...


class AutoCheckMetrics(Protocol):
    def observe(self, entity_type: EntityType, route: Route) -> None:
        """Счётчик маршрутов автопроверки: доля контента, ушедшего в очередь (2.6)."""
        ...


class CaseQueue(Protocol):
    async def open_cases(self, *, limit: int) -> list[OpenCaseView]:
        """Открытые кейсы по сроку: сначала те, у которых срок ближе."""
        ...


AUTO_CHECK: Final = TaskRef("moderation.auto_check", ModerationRequested)
"""Подписчик ModerationRequested: автопроверка объекта (§14.1)."""

RECORD_REREGISTRATION: Final = TaskRef("moderation.record_reregistration", UserRegistered)
"""Подписчик UserRegistered: повторная регистрация после удаления — сигнал риска (2.12)."""
