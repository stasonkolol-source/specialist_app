"""Порты модуля identity (ADR-0020 §3, §5)."""

from collections.abc import Collection, Iterable, Mapping
from datetime import datetime
from typing import Final, Protocol

from app.modules.identity.api import TelegramUserView, UserSummary
from app.modules.identity.application.dto import MeView
from app.modules.identity.domain.consent import Consent, ConsentDocument
from app.modules.identity.domain.deletion import DeletionRequest, HashKind
from app.modules.identity.domain.restriction import Restriction, RestrictionSource
from app.modules.identity.domain.session import Session, SessionId
from app.modules.identity.domain.user import AuthProvider, User
from app.platform.contracts.events.deals import DealCompleted
from app.platform.contracts.events.identity import UserRestricted
from app.platform.kernel.ids import CaseId, DealId, RestrictionId, UserId
from app.platform.kernel.principal import Platform, Principal, Role
from app.platform.queue.port import TaskRef


class UserRepository(Protocol):
    async def get(self, user_id: UserId) -> User: ...

    async def get_for_update(self, user_id: UserId) -> User:
        """Пользователь под блокировкой строки: санкция, нарушение и пересчёт уровня доверия
        одного человека идут по очереди. UserNotFoundError — нет такого."""
        ...

    async def find_by_identity(self, provider: AuthProvider, subject: str) -> User | None:
        """Пользователь для входа; строка заблокирована до конца транзакции: параллельные
        входы одного человека (двойной /start, бот и Mini App разом) идут по очереди."""
        ...

    async def trust_aging_candidates(
        self,
        *,
        now: datetime,
        clean_since: datetime,
        after: tuple[datetime, UserId] | None,
        limit: int,
    ) -> list[User]:
        """Активные пользователи уровня 0, у которых регистрация и последнее нарушение не
        позже `clean_since`, а действующих санкций нет — по (created_at, id) после `after`.
        Строки заблокированы (SKIP LOCKED): два запуска `identity.trust_aging` не берут
        одних и тех же."""
        ...

    async def add(self, user: User) -> None: ...

    async def save(self, user: User) -> None: ...


type DueCursor = tuple[datetime, UserId]
"""Позиция в очереди запросов на удаление: срок исполнения и пользователь."""


class DeletionRepository(Protocol):
    """Запросы на удаление аккаунта (identity.deletion_requests): у пользователя — не больше
    одного ждущего."""

    async def active_for_update(self, user_id: UserId) -> DeletionRequest | None:
        """Ждущий запрос пользователя под блокировкой строки."""
        ...

    async def due(self, now: datetime, *, after: DueCursor | None, limit: int) -> list[DueCursor]:
        """Ждущие запросы, которые пора исполнить, — (срок, пользователь) по порядку после
        `after`, без блокировки: исполнение блокирует строки и проверяет срок заново."""
        ...

    async def add(self, request: DeletionRequest) -> None:
        """Новый запрос; второй ждущий у того же пользователя —
        ConcurrentDeletionRequestError (повтор найдёт первый)."""
        ...

    async def save(self, request: DeletionRequest) -> None: ...


class DeletedIdentities(Protocol):
    """Хэши способов входа удалённых аккаунтов (identity.deleted_identity_hashes, 12 мес)."""

    async def remember(
        self,
        hashes: Mapping[bytes, HashKind],
        *,
        had_sanctions: bool,
        deleted_at: datetime,
        purge_after: datetime,
    ) -> None:
        """Записать хэши; уже известный хэш получает новые даты и признак санкций."""
        ...

    async def find(self, digest: bytes, now: datetime) -> bool | None:
        """Был ли у удалённого аккаунта с этим хэшем санкции; None — хэша нет или он истёк."""
        ...


class SessionRepository(Protocol):
    async def get_for_update(self, session_id: SessionId) -> Session:
        """Сессия под блокировкой строки: два refresh одного токена идут по очереди."""
        ...

    async def active_for_user(self, user_id: UserId, now: datetime) -> list[Session]:
        """Неотозванные и неистёкшие сессии пользователя под блокировкой строк."""
        ...

    async def forget_user(self, user_id: UserId) -> int:
        """Удалить все сессии пользователя (с IP и устройством) — аккаунт удалён (§7.10).
        Сколько удалено. Нужен активный UoW."""
        ...

    async def add(self, session: Session) -> None: ...

    async def save(self, session: Session) -> None: ...


class RoleRepository(Protocol):
    """Роли персонала (identity.user_roles) — простая запись."""

    async def grant(self, user_id: UserId, role: Role, *, granted_by: UserId | None) -> bool:
        """Выдать роль; False — она уже была. UserNotFoundError — нет пользователя."""
        ...


class ConsentRepository(Protocol):
    """Журнал согласий — простая запись (ADR-0020 §5): правило одно — без дублей."""

    async def grant(
        self,
        user_id: UserId,
        versions: Mapping[ConsentDocument, str],
        *,
        source: Platform,
        ip: str | None,
        now: datetime,
    ) -> int:
        """Записать согласия; уже действующая версия документа пропускается.

        Возвращает число новых записей: 0 — повтор. Нужен активный UoW.
        """
        ...

    async def has_active(self, user_id: UserId, documents: Iterable[ConsentDocument]) -> bool:
        """Есть ли у пользователя действующее (не отозванное) согласие с одним из `documents`."""
        ...

    async def withdraw(
        self, user_id: UserId, documents: Iterable[ConsentDocument], *, now: datetime
    ) -> int:
        """Отозвать действующие согласия на документы: `withdrawn_at`, журнал не удаляется.

        Возвращает число отозванных записей. Нужен активный UoW.
        """
        ...


class RestrictionRepository(Protocol):
    """Санкции — простая запись: проверку делает `Restriction.impose`."""

    async def add(
        self,
        user_id: UserId,
        restriction: Restriction,
        *,
        source: RestrictionSource,
        case_id: CaseId | None,
        created_by: UserId | None,
    ) -> RestrictionId:
        """UserNotFoundError — пользователя нет. Нужен активный UoW."""
        ...

    async def lift_for_case(self, case_id: CaseId, *, now: datetime) -> list[UserId]:
        """Снять неснятые санкции кейса (`lifted_at`): пользователь каждой снятой (по одному на
        санкцию). Нужен активный UoW."""
        ...


class IdentityQuery(Protocol):
    async def user_summary(self, user_id: UserId) -> UserSummary | None: ...

    async def user_summaries(self, user_ids: Collection[UserId]) -> dict[UserId, UserSummary]:
        """Пользователи пачкой; кого нет — нет и в ответе."""
        ...

    async def me(self, user_id: UserId) -> MeView | None:
        """Свой профиль; удалённого пользователя нет."""
        ...

    async def by_telegram(self, telegram_id: int) -> TelegramUserView | None:
        """Активный пользователь по Telegram id (бот, ADR-0020 §4 «до use case — только чтение»)."""
        ...

    async def telegram_chat_id(self, user_id: UserId) -> int | None:
        """Telegram id активного пользователя (адрес доставки для notifications)."""
        ...

    async def roles(self, user_id: UserId) -> frozenset[Role]: ...

    async def restrictions(self, user_id: UserId, now: datetime) -> list[Restriction]:
        """Неснятые санкции, которые действуют сейчас или начнутся позже."""
        ...

    async def deleted_among(self, user_ids: Collection[UserId]) -> frozenset[UserId]:
        """Кто из пользователей удалён (или его нет)."""
        ...

    async def restrictions_of(
        self, user_ids: Collection[UserId], now: datetime
    ) -> dict[UserId, list[Restriction]]:
        """Неснятые санкции пользователей, которые действуют сейчас или начнутся позже."""
        ...

    async def consents(self, user_id: UserId) -> list[Consent]:
        """Действующие (не отозванные) согласия."""
        ...

    async def completed_deals(self, user_id: UserId) -> int:
        """Сколько сделок пользователь завершил стороной — уровень доверия 2 (6.1a)."""
        ...


class CompletedDeals(Protocol):
    async def record(self, user_id: UserId, deal_id: DealId, at: datetime) -> bool:
        """Запомнить завершённую сделку стороны; уже была (повтор задачи) — False."""
        ...


class AccessTokenIssuer(Protocol):
    """Выпуск access JWT (platform/security/jwt.py: AccessTokens)."""

    def issue(self, principal: Principal, *, amr: tuple[str, ...]) -> tuple[str, datetime]: ...


class SessionRevocations(Protocol):
    """Немедленный отзыв access-токенов сессии (platform/security/denylist.py)."""

    async def revoke(self, session_id: str) -> None: ...


REVOKE_RESTRICTED_SESSIONS: Final = TaskRef("identity.revoke_restricted_sessions", UserRestricted)
RECORD_COMPLETED_DEAL: Final = TaskRef("identity.record_completed_deal", DealCompleted)
"""Сделка завершена — обеим сторонам факт сделки и пересчёт уровня доверия (6.1a)."""
"""Подписчик UserRestricted: приостановка и бан отзывают сессии сразу, не дожидаясь refresh."""
