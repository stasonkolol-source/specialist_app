"""Наложить санкцию из админки (DEVELOPMENT_PLAN 2.7b; ADR-0020 §1): use case, а не правка строки.

Тем же путём, что решение модерации — фасад `restrict`: событие UserRestricted, уровень доверия —
0. Запись в audit_log от имени сотрудника.
"""

from dataclasses import dataclass
from datetime import datetime

from app.modules.identity.api import IdentityApi, RestrictionIn, RestrictionKind
from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import RestrictionId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ImposeRestrictionCommand:
    user_id: UserId
    kind: RestrictionKind
    reason_code: str
    ends_at: datetime | None
    staff_id: UserId


class ImposeRestriction:
    def __init__(self, uow: UnitOfWork, identity: IdentityApi, audit: AuditLog) -> None:
        self._uow, self._identity, self._audit = uow, identity, audit

    async def __call__(self, cmd: ImposeRestrictionCommand) -> RestrictionId:
        """InvalidRestrictionError — код причины не машинный или срок уже прошёл."""
        async with self._uow:
            restriction_id = await self._identity.restrict(
                RestrictionIn(
                    user_id=cmd.user_id,
                    kind=cmd.kind,
                    reason_code=cmd.reason_code,
                    ends_at=cmd.ends_at,
                    created_by=cmd.staff_id,
                )
            )
            await self._audit.record(
                AuditEntry(
                    action="identity.restriction.imposed",
                    actor_kind=ActorKind.STAFF,
                    actor_id=cmd.staff_id,
                    entity_type="identity.user",
                    entity_id=cmd.user_id,
                    changes={
                        "restriction_id": str(restriction_id),
                        "kind": cmd.kind.value,
                        "reason_code": cmd.reason_code,
                        "ends_at": cmd.ends_at.isoformat() if cmd.ends_at else None,
                    },
                )
            )
        return restriction_id
