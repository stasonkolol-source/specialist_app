"""Отозвать сессии при приостановке и бане (подписчик UserRestricted, ADR-0009).

Refresh и так не проходит при санкции, но access живёт до 15 минут: сессии отзываются
сразу — в БД и в denylist Valkey. Denylist пишется до commit: сбой Valkey откатывает отзыв,
и повтор задачи найдёт те же сессии; после commit их бы уже не было среди активных.
"""

from dataclasses import dataclass

from app.modules.identity.application.ports import SessionRepository, SessionRevocations
from app.modules.identity.domain.restriction import ACCOUNT_BLOCKING, RestrictionKind
from app.modules.identity.domain.session import RevokeReason
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class RevokeRestrictedSessionsCommand:
    user_id: UserId
    kind: RestrictionKind


class RevokeRestrictedSessions:
    def __init__(
        self,
        uow: UnitOfWork,
        sessions: SessionRepository,
        revocations: SessionRevocations,
        clock: Clock,
    ) -> None:
        self._uow, self._sessions = uow, sessions
        self._revocations, self._clock = revocations, clock

    async def __call__(self, cmd: RevokeRestrictedSessionsCommand) -> int:
        """Сколько сессий отозвано; санкции, не блокирующие аккаунт, сессии не трогают."""
        if cmd.kind not in ACCOUNT_BLOCKING:
            return 0
        now = self._clock.now()
        async with self._uow:
            sessions = await self._sessions.active_for_user(cmd.user_id, now)
            for session in sessions:
                session.revoke(reason=RevokeReason.RESTRICTED, now=now)
                await self._sessions.save(session)
                await self._revocations.revoke(session.sid)
        return len(sessions)
