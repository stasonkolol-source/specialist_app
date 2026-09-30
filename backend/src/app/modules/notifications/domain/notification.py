"""Уведомление и его доставка (ARCHITECTURE §11.2, §7.3).

Уведомление — запись центра уведомлений (S42) и источник доставок; `dedupe_key` делает
повтор события безвредным. Доставка — отправка в один канал (личный чат с ботом) не раньше
`not_before`: тихие часы, позже — дебаунс и дайджест.
"""

from enum import StrEnum
from typing import NewType
from uuid import UUID

NotificationId = NewType("NotificationId", UUID)
DeliveryId = NewType("DeliveryId", UUID)


class DeliveryStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
    """Bot API отказал окончательно (400) — шаг 2.3b."""
    SUPPRESSED = "suppressed"
    """Не отправлено по нашей воле: канал выключен или получатель удалён."""
