"""Статус Founding (§15.2, ADR-0014): `cli founding-mark --tg-id <id>` (DEVELOPMENT_PLAN 2.8a).

Первые 150–200 специалистов — Founding: флаг профиля; бейдж и бесплатный Pro — v1. Действие
в админке появится в 2.7b. Отметка пишется в audit_log; повтор — без записи.
"""

from dataclasses import dataclass

from app.modules.identity.api import IdentityApi
from app.modules.specialists.application.ports import ProfileRepository
from app.modules.specialists.domain.profile import ProfileId
from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.db.port import UnitOfWork


@dataclass(frozen=True, slots=True, kw_only=True)
class MarkFoundingCommand:
    telegram_id: int


@dataclass(frozen=True, slots=True, kw_only=True)
class FoundingMarked:
    profile_id: ProfileId
    marked: bool
    """False — отметка уже была."""


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
            marked = profile.mark_founding()
            if marked:
                await self._profiles.save(profile)
                await self._audit.record(
                    AuditEntry(
                        action="specialists.profile.founding_marked",
                        actor_kind=ActorKind.SYSTEM,
                        entity_type="specialists.profile",
                        entity_id=profile.id,
                    )
                )
        return FoundingMarked(profile_id=profile.id, marked=marked)
