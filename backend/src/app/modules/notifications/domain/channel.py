"""Каналы доставки (ARCHITECTURE §11.1, §7.3 `notifications.channels`, ADR-0011).

Канал — куда доставлять уведомления пользователю: личный чат с ботом (MVP), позже токены
APNs/FCM и e-mail (этап 2). Бот не пишет первым: канал `telegram` появляется, когда
пользователь разрешил боту писать — `/start` в боте или `requestWriteAccess` в Mini App.
Повторное разрешение идемпотентно; выключенный канал (бот заблокирован, 403 — шаг 2.3)
оно включает снова. Правило одно, поэтому канал — простая запись без агрегата (ADR-0020 §5).
"""

from enum import StrEnum


class ChannelKind(StrEnum):
    TELEGRAM = "telegram"
    APNS = "apns"
    FCM = "fcm"
    EMAIL = "email"


class GrantedVia(StrEnum):
    """Как пользователь разрешил доставку по каналу."""

    BOT_START = "bot_start"
    """`/start` в личном чате с ботом."""
    MINI_APP = "mini_app"
    """`requestWriteAccess` в Mini App → `POST /me/telegram/write-access`."""
