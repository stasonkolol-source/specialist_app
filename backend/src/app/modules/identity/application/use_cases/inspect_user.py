"""Карточка пользователя персоналу (Admin API `GET /users/{id}`, DEVELOPMENT_PLAN 2.7b; §13.2).

Без ПД — статус, доверие, активность в identity (вход, сессии, завершённые сделки), роли и все
санкции, со снятыми. С ПД (имя, телефон, Telegram) — только по флагу точки входа (support и
admin): чтение ПД и запись `identity.user.pii_viewed` в audit_log — одной транзакцией, как
просмотр доказательств спора (InspectDispute): ПД без записи о просмотре не выходят. Кто, когда,
с какого адреса и по какому кейсу — в записи. Роль проверяет точка входа.
"""

from dataclasses import dataclass

from app.modules.identity.application.dto import PersonalData, StaffUserCard
from app.modules.identity.application.ports import IdentityQuery
from app.modules.identity.errors import UserNotFoundError
from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import CaseId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class InspectUserCommand:
    user_id: UserId
    staff_id: UserId
    personal_data: bool
    """Показать ПД: точка входа решает по роли сотрудника."""
    case_id: CaseId | None = None
    """По какому кейсу смотрят (§13.2) — в запись аудита."""
    ip: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class UserInspection:
    card: StaffUserCard
    personal_data: PersonalData | None


class InspectUser:
    def __init__(
        self, uow: UnitOfWork, query: IdentityQuery, audit: AuditLog, clock: Clock
    ) -> None:
        self._uow, self._query, self._audit, self._clock = uow, query, audit, clock

    async def __call__(self, cmd: InspectUserCommand) -> UserInspection:
        """UserNotFoundError — такого пользователя нет."""
        card = await self._query.staff_card(cmd.user_id, self._clock.now())
        if card is None:
            raise UserNotFoundError(user_id=cmd.user_id)
        if not cmd.personal_data:
            return UserInspection(card=card, personal_data=None)
        async with self._uow:  # просмотр ПД и запись о нём — вместе
            personal = await self._query.personal_data(cmd.user_id)
            if personal is None:
                raise UserNotFoundError(user_id=cmd.user_id)
            await self._audit.record(
                AuditEntry(
                    action="identity.user.pii_viewed",
                    actor_kind=ActorKind.STAFF,
                    actor_id=cmd.staff_id,
                    entity_type="identity.user",
                    entity_id=cmd.user_id,
                    changes={
                        "fields": list(PersonalData.FIELDS),
                        "case_id": str(cmd.case_id) if cmd.case_id is not None else None,
                    },
                    ip=cmd.ip,
                )
            )
        return UserInspection(card=card, personal_data=personal)
