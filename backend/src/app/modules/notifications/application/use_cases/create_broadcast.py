"""Черновик рассылки (DEVELOPMENT_PLAN 2.7b): раздел «Рассылки» админки, только admin.

Текст — на русском и сербском (§7.4: второй алфавит — по цепочке запасных), кнопка — код deep
link (§11.4) или «Хочу узнать первым» (лист ожидания Pro, Q24), аудитория — сегмент и город
среди тех, кто включил группу рассылки. Создание пишется в audit_log от имени сотрудника.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from app.modules.notifications.application.ports import BroadcastRepository
from app.modules.notifications.domain.broadcast import (
    Audience,
    Broadcast,
    BroadcastAction,
    BroadcastId,
    Targeting,
)
from app.modules.notifications.domain.catalog import EventGroup
from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.errors import DomainValidationError
from app.platform.kernel.ids import CityId, UserId, new_id
from app.platform.kernel.localized import LocalizedText
from app.platform.telegram.deeplinks import parse_start_param


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateBroadcastCommand:
    staff_id: UserId
    text: Mapping[str, str]
    """Тексты по кодам локалей (`ru`, `sr-Latn`, `sr-Cyrl`); пустые не считаются."""
    group: EventGroup = EventGroup.MARKETING
    audience: Audience = Audience.ALL
    city_id: CityId | None = None
    link: str | None = None
    action: BroadcastAction | None = None


class CreateBroadcast:
    def __init__(
        self, uow: UnitOfWork, broadcasts: BroadcastRepository, audit: AuditLog, clock: Clock
    ) -> None:
        self._uow, self._broadcasts, self._audit, self._clock = uow, broadcasts, audit, clock

    async def __call__(self, cmd: CreateBroadcastCommand) -> BroadcastId:
        if cmd.link is not None and parse_start_param(cmd.link) is None:
            raise DomainValidationError(field="link", value=cmd.link)
        broadcast = Broadcast(
            id=BroadcastId(new_id()),
            text=LocalizedText.from_mapping({k: v for k, v in cmd.text.items() if v.strip()}),
            group=cmd.group,
            targeting=Targeting(audience=cmd.audience, city_id=cmd.city_id),
            link=cmd.link,
            action=cmd.action,
            created_by=cmd.staff_id,
            created_at=self._clock.now(),
        )
        async with self._uow:
            await self._broadcasts.add(broadcast)
            await self._audit.record(
                AuditEntry(
                    action="notifications.broadcast.created",
                    actor_kind=ActorKind.STAFF,
                    actor_id=cmd.staff_id,
                    entity_type="notifications.broadcast",
                    entity_id=broadcast.id,
                    changes={
                        "group": broadcast.group.value,
                        "audience": broadcast.targeting.audience.value,
                        "city_id": broadcast.targeting.city_id,
                        "link": broadcast.link,
                        "action": broadcast.action.value if broadcast.action else None,
                        "locales": sorted(locale.value for locale in broadcast.text.values),
                    },
                )
            )
        return broadcast.id
