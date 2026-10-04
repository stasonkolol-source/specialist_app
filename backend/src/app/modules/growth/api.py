"""Контракт модуля growth для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из growth только этот файл.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.platform.kernel.ids import UserId


class ShareTarget(StrEnum):
    """Чем делятся (7.4): только публичным — карточкой специалиста и заявкой."""

    SPECIALIST = "specialist"
    JOB = "job"


@dataclass(frozen=True, slots=True, kw_only=True)
class ShareText:
    """Карточка для чата на языке того, кто делится. Видна ли сущность всем и что о ней
    показать, решает вызывающий (BFF): growth не видит specialists и jobs (DAG §5.4)."""

    title: str
    """Заголовок результата в окне выбора чата."""
    description: str | None
    text: str
    """HTML сообщения без ссылки (параметры экранированы): ссылка — кнопкой."""
    button_text: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ShareRequest:
    sharer_id: UserId | None
    """None — гость: ссылка без кода приглашения и без карточки."""
    target: ShareTarget
    target_id: UUID
    card: ShareText


@dataclass(frozen=True, slots=True, kw_only=True)
class SharedLink:
    start_param: str
    """Код startapp: `s_<base62>` или `j_<base62>`, у вошедшего — с `_r<code>`."""
    url: str
    """`https://t.me/<bot>?startapp=<код>`."""
    prepared_message_id: str | None
    """id карточки для `WebApp.shareMessage`; None — клиент делится ссылкой."""


class GrowthApi(Protocol):
    async def share(self, request: ShareRequest) -> SharedLink:
        """Ссылка «Поделиться» и карточка для чата (POST /share). Сама транзакция: вызывать
        вне UoW вызывающего."""
        ...
