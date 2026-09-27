"""Порты модуля identity (ADR-0020 §3, §5)."""

from datetime import datetime
from typing import Protocol

from app.modules.identity.api import UserSummary
from app.modules.identity.application.dto import MeView
from app.modules.identity.domain.restriction import Restriction
from app.modules.identity.domain.session import Session, SessionId
from app.modules.identity.domain.user import AuthProvider, User
from app.platform.kernel.ids import UserId
from app.platform.kernel.principal import Principal, Role


class UserRepository(Protocol):
    async def get(self, user_id: UserId) -> User: ...

    async def find_by_identity(self, provider: AuthProvider, subject: str) -> User | None: ...

    async def add(self, user: User) -> None: ...

    async def save(self, user: User) -> None: ...


class SessionRepository(Protocol):
    async def get_for_update(self, session_id: SessionId) -> Session:
        """Сессия под блокировкой строки: два refresh одного токена идут по очереди."""
        ...

    async def add(self, session: Session) -> None: ...

    async def save(self, session: Session) -> None: ...


class IdentityQuery(Protocol):
    async def user_summary(self, user_id: UserId) -> UserSummary | None: ...

    async def me(self, user_id: UserId) -> MeView | None:
        """Свой профиль; удалённого пользователя нет."""
        ...

    async def roles(self, user_id: UserId) -> frozenset[Role]: ...

    async def restrictions(self, user_id: UserId, now: datetime) -> list[Restriction]:
        """Неснятые санкции, которые действуют сейчас или начнутся позже."""
        ...


class AccessTokenIssuer(Protocol):
    """Выпуск access JWT (platform/security/jwt.py: AccessTokens)."""

    def issue(self, principal: Principal, *, amr: tuple[str, ...]) -> tuple[str, datetime]: ...


class SessionRevocations(Protocol):
    """Немедленный отзыв access-токенов сессии (platform/security/denylist.py)."""

    async def revoke(self, session_id: str) -> None: ...
