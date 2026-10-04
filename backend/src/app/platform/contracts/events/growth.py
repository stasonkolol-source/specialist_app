"""События модуля growth (ADR-0020 §2; ARCHITECTURE §11.4; DEVELOPMENT_PLAN 7.4). Подписчик —
аналитика: K-фактор шаринга считается из `share_created`, `attribution_recorded` и
`user_registered`."""

from dataclasses import dataclass

from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ShareCreated(DomainEvent):
    """Вошедший взял ссылку «Поделиться» (S08, S10, S15, S21, S23) — со своим кодом `_r`.

    `entity_type` — чем делятся: `specialist` или `job`; `prepared` — Telegram принял карточку
    для `shareMessage` (иначе клиент делится ссылкой). Ушло ли сообщение в чат, знает только
    клиент: событие — о ссылке."""

    event_type = "growth.ShareCreated"
    sharer_id: UserId
    entity_type: str
    prepared: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class AttributionRecorded(DomainEvent):
    """Записано первое касание нового пользователя (`growth.attributions`).

    `source` — тип ссылки (LinkSource кодека); `has_referral` — в коде был суффикс `_r`:
    пришёл по чужой ссылке «Поделиться» или по коду канала."""

    event_type = "growth.AttributionRecorded"
    user_id: UserId
    source: str
    has_referral: bool
