"""Выход: отзыв своей сессии и её access-токенов (ADR-0009)."""

from dataclasses import dataclass

from app.modules.identity.application.ports import SessionRepository, SessionRevocations
from app.modules.identity.domain.session import RevokeReason, SessionId
from app.modules.identity.errors import SessionNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class LogoutCommand:
    actor_id: UserId
    session_id: SessionId


class Logout:
    def __init__(
        self,
        uow: UnitOfWork,
        sessions: SessionRepository,
        revocations: SessionRevocations,
        clock: Clock,
    ) -> None:
        self._uow, self._sessions, self._revocations, self._clock = (
            uow,
            sessions,
            revocations,
            clock,
        )

    async def __call__(self, cmd: LogoutCommand) -> None:
        async with self._uow:
            session = await self._sessions.get_for_update(cmd.session_id)
            if session.user_id != cmd.actor_id:
                raise SessionNotFoundError(session_id=cmd.session_id)  # чужая сессия не видна
            session.revoke(reason=RevokeReason.LOGOUT, now=self._clock.now())
            await self._sessions.save(session)
        await self._revocations.revoke(session.sid)
