"""Санкции из админки (DEVELOPMENT_PLAN 2.7b; ADR-0020 §1): наложить и снять — через use case, а
не правкой строки. Наложение идёт тем же путём, что решение модерации (фасад `restrict`: событие
UserRestricted, уровень доверия — 0), снятие — событием UserRestrictionsLifted. Оба — в audit_log
от имени сотрудника.
"""

from dataclasses import dataclass
from datetime import datetime

from app.modules.identity.api import IdentityApi, RestrictionIn, RestrictionKind
from app.modules.identity.application.ports import RestrictionRepository
from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.contracts.events.identity import UserRestrictionsLifted
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import RestrictionId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ImposeRestrictionCommand:
    user_id: UserId
    kind: RestrictionKind
    reason_code: str
    ends_at: datetime | None
    staff_id: UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class LiftRestrictionCommand:
    restriction_id: RestrictionId
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


class LiftRestriction:
    def __init__(
        self, uow: UnitOfWork, restrictions: RestrictionRepository, audit: AuditLog, clock: Clock
    ) -> None:
        self._uow, self._restrictions, self._audit, self._clock = uow, restrictions, audit, clock

    async def __call__(self, cmd: LiftRestrictionCommand) -> bool:
        """False — санкции нет или она уже снята."""
        now = self._clock.now()
        async with self._uow:
            user_id = await self._restrictions.lift(cmd.restriction_id, now=now)
            if user_id is None:
                return False
            self._uow.add_event(UserRestrictionsLifted(user_id=user_id, occurred_at=now))
            await self._audit.record(
                AuditEntry(
                    action="identity.restriction.lifted",
                    actor_kind=ActorKind.STAFF,
                    actor_id=cmd.staff_id,
                    entity_type="identity.user",
                    entity_id=user_id,
                    changes={"restriction_id": str(cmd.restriction_id)},
                )
            )
        return True
