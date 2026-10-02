"""Данные callback-кнопок бота (ARCHITECTURE §11.3): `<действие>:<id base62>[:<аргумент>]`.

Кнопку рисует один модуль (уведомление — notifications), нажатие обрабатывает другой (бот
модуля сущности), поэтому формат общий и живёт здесь, как кодек deep links. Bot API
ограничивает данные 64 байтами: действие — две буквы, id — UUID в base62 (22 символа),
аргумент — код из закрытого списка или второй id в base62 (`ref_arg`): «Откликнуться шаблоном» —
`jr:<заявка>:<шаблон>`, 48 байт. Кнопки одного модуля, которые он сам и обрабатывает (`avail:` в
specialists), кодек не нужен.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.platform.telegram.deeplinks import base62_to_uuid, uuid_to_base62

MAX_CALLBACK_DATA: Final = 64
"""Предел Bot API для `callback_data`, байт."""
_ARG: Final = re.compile(r"[A-Za-z0-9_]{1,24}")
"""Код (`found`, `hired_here`) или id в base62."""


class CallbackAction(StrEnum):
    JOB_EXTEND = "jx"
    """Продлить заявку — кнопка `job.expiring` и `job.expired`."""
    JOB_CLOSE = "jc"
    """Закрыть заявку: без аргумента — спросить причину, `found` — спросить, где нашли
    исполнителя, с причиной (`hired_here`, …) — закрыть."""
    JOB_RESPOND = "jr"
    """Откликнуться шаблоном (`job.invited`, 5.6; `job.matched`, 5.7): аргумент — id шаблона."""


@dataclass(frozen=True, slots=True)
class CallbackData:
    action: CallbackAction
    id: UUID
    arg: str | None = None

    def __post_init__(self) -> None:
        if self.arg is not None and _ARG.fullmatch(self.arg) is None:
            raise ValueError(f"callback argument {self.arg!r} is not a code")


def encode_callback(data: CallbackData) -> str:
    parts = [data.action.value, uuid_to_base62(data.id)]
    if data.arg is not None:
        parts.append(data.arg)
    return ":".join(parts)


def parse_callback(raw: str | None) -> CallbackData | None:
    """Данные нажатой кнопки; None — не наш формат или испорченные данные."""
    if not raw or len(raw.encode()) > MAX_CALLBACK_DATA:
        return None
    parts = raw.split(":")
    if len(parts) not in {2, 3}:
        return None
    try:
        action = CallbackAction(parts[0])
    except ValueError:
        return None
    entity = base62_to_uuid(parts[1])
    arg = parts[2] if len(parts) == 3 else None
    if entity is None or (arg is not None and _ARG.fullmatch(arg) is None):
        return None
    return CallbackData(action, entity, arg)


def ref_arg(ref: UUID) -> str:
    """Второй id аргументом кнопки: «Откликнуться шаблоном» — id шаблона."""
    return uuid_to_base62(ref)


def arg_ref(arg: str | None) -> UUID | None:
    """id из аргумента кнопки; не id — None."""
    return base62_to_uuid(arg) if arg else None
