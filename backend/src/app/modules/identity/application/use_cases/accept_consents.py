"""Одна галочка S02c: правила площадки с 18+ и политика (POST /me/consents, ADR-0018).

Версии, которые видел пользователь, сверяются с действующими из client-config; повтор
той же версии ничего не пишет — запрос идемпотентен.
"""

from dataclasses import dataclass

from app.modules.identity.application.ports import ConsentRepository, UserRepository
from app.modules.identity.domain.policies import one_tick_consents
from app.platform.config.port import LegalVersions
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId
from app.platform.kernel.principal import Platform


@dataclass(frozen=True, slots=True, kw_only=True)
class AcceptConsentsCommand:
    actor_id: UserId
    terms_version: str
    privacy_version: str
    source: Platform
    """Платформа сессии, с которой дано согласие (журнал ZET/ZZPL)."""
    ip: str | None = None


class AcceptConsents:
    def __init__(
        self,
        uow: UnitOfWork,
        users: UserRepository,
        consents: ConsentRepository,
        legal: LegalVersions,
        clock: Clock,
    ) -> None:
        self._uow, self._users, self._consents = uow, users, consents
        self._legal, self._clock = legal, clock

    async def __call__(self, cmd: AcceptConsentsCommand) -> int:
        """Число новых записей журнала: 0 — всё уже было принято."""
        versions = one_tick_consents(
            await self._legal.legal_versions(),
            terms_version=cmd.terms_version,
            privacy_version=cmd.privacy_version,
        )
        async with self._uow:
            user = await self._users.get(cmd.actor_id)
            user.ensure_active()
            return await self._consents.grant(
                user.id, versions, source=cmd.source, ip=cmd.ip, now=self._clock.now()
            )
