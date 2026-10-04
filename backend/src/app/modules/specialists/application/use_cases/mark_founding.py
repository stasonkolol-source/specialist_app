"""Статус Founding (§15.2, ADR-0014): `cli founding-mark --tg-id <id>` (DEVELOPMENT_PLAN 2.8a)
и действие «Founding» в админке (2.7b).

Первые 150–200 специалистов — Founding: флаг профиля; бейдж и бесплатный Pro — v1 (в MVP бейджа
нет: на утверждённых макетах его нет, клиенту флаг уже отдаёт карточка S08 — `is_founding`).
События у отметки нет: подписчиков нет, поиск флаг не индексирует. Каждая смена — в audit_log
(из cli — от имени системы, из админки — от имени сотрудника); повтор — без записи.
"""

from dataclasses import dataclass
from typing import Final

from app.modules.identity.api import IdentityApi
from app.modules.specialists.application.ports import ProfileRepository
from app.modules.specialists.domain.profile import ProfileId
from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId

ENTITY: Final = "specialists.profile"


@dataclass(frozen=True, slots=True, kw_only=True)
class MarkFoundingCommand:
    telegram_id: int


@dataclass(frozen=True, slots=True, kw_only=True)
class SetFoundingCommand:
    profile_id: ProfileId
    founding: bool
    """False — снять ошибочную отметку."""
    staff_id: UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class FoundingMarked:
    profile_id: ProfileId
    marked: bool
    """False — статус уже был таким."""


def _entry(profile_id: ProfileId, *, founding: bool, staff_id: UserId | None) -> AuditEntry:
    return AuditEntry(
        action=f"{ENTITY}.{'founding_marked' if founding else 'founding_unmarked'}",
        actor_kind=ActorKind.SYSTEM if staff_id is None else ActorKind.STAFF,
        actor_id=staff_id,
        entity_type=ENTITY,
        entity_id=profile_id,
    )


class MarkFounding:
    def __init__(
        self, uow: UnitOfWork, profiles: ProfileRepository, identity: IdentityApi, audit: AuditLog
    ) -> None:
        self._uow, self._profiles, self._identity, self._audit = uow, profiles, identity, audit

    async def __call__(self, cmd: MarkFoundingCommand) -> FoundingMarked | None:
        """None — нет такого пользователя или у него нет профиля исполнителя."""
        user = await self._identity.by_telegram(cmd.telegram_id)
        if user is None:
            return None
        async with self._uow:
            profile = await self._profiles.of_user(user.id)
            if profile is None:
                return None
            marked = profile.set_founding(founding=True)
            if marked:
                await self._profiles.save(profile)
                await self._audit.record(_entry(profile.id, founding=True, staff_id=None))
        return FoundingMarked(profile_id=profile.id, marked=marked)


class SetFounding:
    """Админка: отметить профиль Founding или снять отметку — от имени сотрудника."""

    def __init__(self, uow: UnitOfWork, profiles: ProfileRepository, audit: AuditLog) -> None:
        self._uow, self._profiles, self._audit = uow, profiles, audit

    async def __call__(self, cmd: SetFoundingCommand) -> FoundingMarked:
        """ProfileNotFoundError — нет такого профиля или он удалён."""
        async with self._uow:
            profile = await self._profiles.get_for_update(cmd.profile_id)
            changed = profile.set_founding(founding=cmd.founding)
            if changed:
                await self._profiles.save(profile)
                await self._audit.record(
                    _entry(profile.id, founding=cmd.founding, staff_id=cmd.staff_id)
                )
        return FoundingMarked(profile_id=profile.id, marked=changed)
