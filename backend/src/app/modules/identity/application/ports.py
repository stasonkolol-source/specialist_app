"""Порты модуля identity (ADR-0020 §3, §5)."""

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

from app.modules.identity.api import TelegramUserView, UserSummary
from app.modules.identity.application.dto import MeView
from app.modules.identity.domain.consent import Consent, ConsentDocument
from app.modules.identity.domain.restriction import Restriction, RestrictionSource
from app.modules.identity.domain.session import Session, SessionId
from app.modules.identity.domain.user import AuthProvider, User
from app.platform.kernel.ids import CaseId, RestrictionId, UserId
from app.platform.kernel.principal import Platform, Principal, Role


class UserRepository(Protocol):
    async def get(self, user_id: UserId) -> User: ...

    async def find_by_identity(self, provider: AuthProvider, subject: str) -> User | None:
        """Пользователь для входа; строка заблокирована до конца транзакции: параллельные
        входы одного человека (двойной /start, бот и Mini App разом) идут по очереди."""
        ...

    async def add(self, user: User) -> None: ...

    async def save(self, user: User) -> None: ...


class SessionRepository(Protocol):
    async def get_for_update(self, session_id: SessionId) -> Session:
        """Сессия под блокировкой строки: два refresh одного токена идут по очереди."""
        ...

    async def add(self, session: Session) -> None: ...

    async def save(self, session: Session) -> None: ...


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


class IdentityQuery(Protocol):
    async def user_summary(self, user_id: UserId) -> UserSummary | None: ...

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

    async def consents(self, user_id: UserId) -> list[Consent]:
        """Действующие (не отозванные) согласия."""
        ...


class AccessTokenIssuer(Protocol):
    """Выпуск access JWT (platform/security/jwt.py: AccessTokens)."""

    def issue(self, principal: Principal, *, amr: tuple[str, ...]) -> tuple[str, datetime]: ...


class SessionRevocations(Protocol):
    """Немедленный отзыв access-токенов сессии (platform/security/denylist.py)."""

    async def revoke(self, session_id: str) -> None: ...
