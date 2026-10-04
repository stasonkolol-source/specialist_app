"""Порты модуля moderation (ADR-0020 §3, §5)."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final, Protocol
from uuid import UUID

from app.modules.moderation.application.dto import ImportRulesResult, OpenCaseView, QueueSla
from app.modules.moderation.domain.cases import Case, EntityType
from app.modules.moderation.domain.pipeline import Route
from app.modules.moderation.domain.reports import Report, ReportStatus
from app.modules.moderation.domain.risk import RiskSignal
from app.modules.moderation.domain.rules import ContentRule, RuleSet
from app.modules.moderation.domain.sanctions import Sanction, SanctionStep
from app.platform.ai.port import ContentKind
from app.platform.contracts.events.deals import (
    DealDisputed,
    DisputeAnswered,
    DisputeUnanswered,
    DisputeWithdrawn,
)
from app.platform.contracts.events.identity import UserRegistered
from app.platform.contracts.events.media import MediaReady
from app.platform.contracts.events.moderation import CaseOpened, ModerationRequested
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
        """Открытый кейс объекта под блокировкой строки (апелляции — не в счёт)."""
        ...

    async def appeal_for(self, case_id: CaseId) -> Case | None:
        """Апелляция на решение (в любом статусе) под блокировкой строки."""
        ...

    async def get(self, case_id: CaseId) -> Case | None:
        """Кейс без блокировки: показать (карточка в чате модераторов)."""
        ...

    async def add(self, case: Case) -> None:
        """CaseAlreadyOpenError — параллельный запрос только что открыл кейс того же объекта;
        AppealAlreadyFiledError — апелляцию на то же решение."""
        ...

    async def save(self, case: Case) -> None: ...


class SanctionRepository(Protocol):
    async def counted(self, user_id: UserId, now: datetime) -> int:
        """Несгоревшие и неотменённые предупреждения и страйки 1–2 пользователя."""
        ...

    async def latest_case(self, user_id: UserId, steps: Collection[SanctionStep]) -> CaseId | None:
        """Кейс последней неотменённой санкции пользователя из этих ступеней."""
        ...

    async def revoke_for_case(self, case_id: CaseId, now: datetime) -> int:
        """Апелляция удовлетворена: ступени по кейсу отменены, в лестнице не считаются.
        Сколько отменено. Нужен активный UoW."""
        ...

    async def add(self, sanction: Sanction) -> None: ...


class RiskSignals(Protocol):
    async def add(self, signals: Sequence[RiskSignal]) -> int:
        """Записать сигналы; с уже записанным `dedupe_key` — пропустить. Сколько новых."""
        ...


class ReportRepository(Protocol):
    """Жалобы (4.7) — простая запись: правило «одна открытая жалоба человека на объект» держит
    частичный уникальный индекс."""

    async def open_of(
        self, reporter_id: UserId, target_type: EntityType, target_id: UUID
    ) -> Report | None:
        """Открытая жалоба этого человека на объект."""
        ...

    async def add(self, report: Report) -> None:
        """ReportAlreadyOpenError — параллельный запрос только что записал такую же."""
        ...

    async def close_for_case(
        self,
        case_id: CaseId,
        *,
        status: ReportStatus,
        resolved_by: UserId | None,
        resolution: str | None,
        now: datetime,
    ) -> int:
        """Решение по кейсу закрывает его открытые жалобы. Сколько закрыто. Нужен активный UoW."""
        ...


class ReportTargets(Protocol):
    """На кого жалоба: автор объекта, который жалующийся видит (фасады модулей-владельцев)."""

    async def subject(
        self, target_type: EntityType, target_id: UUID, reporter_id: UserId
    ) -> UserId | None:
        """Чей объект; None — объекта нет или жалующийся его не видит (чужая переписка, снятый
        профиль, удалённый аккаунт)."""
        ...

    async def counterpart(self, conversation_id: UUID, reporter_id: UserId) -> UserId | None:
        """Вторая сторона диалога жалующегося; None — диалога нет или он не участник."""
        ...


class ReportQuota(Protocol):
    async def take(self, reporter_id: UserId) -> None:
        """Засчитать жалобу; двадцать первая за сутки — ReportsLimitError (429)."""
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


class ModeratorsChat(Protocol):
    """Чат модераторов (2.5b, infrastructure/chat.py): карточка кейса с кнопками решения."""

    @property
    def enabled(self) -> bool:
        """Чат задан (`TELEGRAM_MODERATORS_CHAT_ID`, K29); нет — кейсы решают командами `cli`."""
        ...

    async def post(self, case: Case) -> None:
        """Прислать карточку. Bot API недоступен — ExternalServiceError (повтор задачи)."""
        ...


class CaseQueue(Protocol):
    async def open_cases(self, *, limit: int) -> list[OpenCaseView]:
        """Открытые кейсы по сроку: сначала те, у которых срок ближе."""
        ...


AUTO_CHECK: Final = TaskRef("moderation.auto_check", ModerationRequested)
"""Подписчик ModerationRequested: автопроверка объекта (§14.1)."""

RECORD_REREGISTRATION: Final = TaskRef("moderation.record_reregistration", UserRegistered)
"""Подписчик UserRegistered: повторная регистрация после удаления — сигнал риска (2.12)."""

OPEN_DISPUTE_CASE: Final = TaskRef("moderation.open_dispute_case", DealDisputed)
"""Спор открыт (6.1c): кейс `dispute` в очереди P1 (угрозы — P0)."""
NOTE_DISPUTE_ANSWER: Final = TaskRef("moderation.note_dispute_answer", DisputeAnswered)
"""Вторая сторона ответила: повод «answered» и её фото — в кейс."""
NOTE_DISPUTE_UNANSWERED: Final = TaskRef("moderation.note_dispute_unanswered", DisputeUnanswered)
"""48 ч без ответа: пометка «нет ответа» в кейсе."""
CLOSE_DISPUTE_CASE: Final = TaskRef("moderation.close_dispute_case", DisputeWithdrawn)
"""Спор отозван: кейс закрыт без решения."""
POST_CASE_CARD: Final = TaskRef("moderation.post_case_card", CaseOpened)
"""Новый кейс (2.5b): карточка в чате модераторов."""
CHECK_DUPLICATES: Final = TaskRef("moderation.check_duplicates", MediaReady)
"""Фото портфолио обработано (7.6): такое же у других аккаунтов — кейс P2 (ADR-0016 L6)."""
