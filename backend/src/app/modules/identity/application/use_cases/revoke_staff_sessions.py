"""Закрыть сессии админки сотрудника: `cli staff-revoke` (DEVELOPMENT_PLAN 2.7b, 8.4; ASVS V7).

Cookie персонала подписана, но на сервере не хранится: выйти из чужого браузера (украденный
ноутбук, увольнение) можно только новым поколением входа (`session_epoch`) — cookie прежнего
поколения больше не открывает ни админку, ни Admin API, следующий же запрос ведёт на вход. С
`remove_login` вход удаляется совсем: войти снова можно только после `staff-create`. Роли не
трогаются — их снимает отдельная команда. Каждое закрытие пишется в audit_log.
"""

from dataclasses import dataclass

from app.modules.identity.application.dto import StaffSessionsRevoked
from app.modules.identity.application.ports import StaffCredentials, UserRepository
from app.modules.identity.domain.user import AuthProvider
from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.db.port import UnitOfWork


@dataclass(frozen=True, slots=True, kw_only=True)
class RevokeStaffSessionsCommand:
    telegram_id: int
    """Кто: сотрудник по Telegram id (в логи не пишется)."""
    remove_login: bool = False


class RevokeStaffSessions:
    def __init__(
        self,
        uow: UnitOfWork,
        users: UserRepository,
        credentials: StaffCredentials,
        audit: AuditLog,
    ) -> None:
        self._uow, self._users, self._credentials, self._audit = uow, users, credentials, audit

    async def __call__(self, cmd: RevokeStaffSessionsCommand) -> StaffSessionsRevoked | None:
        """None — такого пользователя нет или у него нет входа в админку."""
        async with self._uow:
            user = await self._users.find_by_identity(AuthProvider.TELEGRAM, str(cmd.telegram_id))
            if user is None:
                return None
            if not await self._credentials.revoke_sessions(user.id, remove_login=cmd.remove_login):
                return None
            await self._audit.record(
                AuditEntry(
                    action="identity.staff.sessions_revoked",
                    actor_kind=ActorKind.SYSTEM,
                    entity_type="identity.user",
                    entity_id=user.id,
                    changes={"login_removed": cmd.remove_login},
                )
            )
        return StaffSessionsRevoked(user_id=user.id, login_removed=cmd.remove_login)
