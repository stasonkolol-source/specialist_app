"""Выдать роль персонала: `cli staff-grant --tg-id <id> --role …` (DEVELOPMENT_PLAN 2.5a).

Список персонала — K29. Роль появляется в JWT (`roles`) при следующем выпуске access; пароль,
TOTP и вход в SQLAdmin — 2.7a. Выдача пишется в audit_log; повторная выдача — без записи.
"""

from dataclasses import dataclass

from app.modules.identity.application.dto import StaffRoleGranted
from app.modules.identity.application.ports import RoleRepository, UserRepository
from app.modules.identity.domain.user import AuthProvider, UserStatus
from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.db.port import UnitOfWork
from app.platform.kernel.principal import Role


@dataclass(frozen=True, slots=True, kw_only=True)
class GrantStaffRoleCommand:
    telegram_id: int
    """Кому: Telegram id сотрудника (в логи не пишется)."""
    role: Role


class GrantStaffRole:
    def __init__(
        self, uow: UnitOfWork, users: UserRepository, roles: RoleRepository, audit: AuditLog
    ) -> None:
        self._uow, self._users, self._roles, self._audit = uow, users, roles, audit

    async def __call__(self, cmd: GrantStaffRoleCommand) -> StaffRoleGranted | None:
        """None — такой пользователь не входил в бот или Mini App (или удалён)."""
        async with self._uow:
            user = await self._users.find_by_identity(AuthProvider.TELEGRAM, str(cmd.telegram_id))
            if user is None or user.status is UserStatus.DELETED:
                return None
            granted = await self._roles.grant(user.id, cmd.role, granted_by=None)
            if granted:
                await self._audit.record(
                    AuditEntry(
                        action="identity.role.granted",
                        actor_kind=ActorKind.SYSTEM,
                        entity_type="identity.user",
                        entity_id=user.id,
                        changes={"role": cmd.role.value},
                    )
                )
        return StaffRoleGranted(user_id=user.id, role=cmd.role, granted=granted)
