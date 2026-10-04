"""Рассылка из админки (DEVELOPMENT_PLAN 2.7b, ARCHITECTURE §8.5 `/broadcasts`, §11.2).

Рассылка — объявление через бота: текст на языках интерфейса, необязательная кнопка в Mini App
(код deep link) или «Хочу узнать первым» (лист ожидания Pro, Q24), аудитория и группа согласия.
Путь: черновик → запланирована (старт позже) → идёт → завершена; отменить можно до завершения.
Каждому получателю — уведомление типа `broadcast` с ключом `broadcast:<рассылка>:<получатель>`:
повтор разбора аудитории второго сообщения не создаёт, а отправка идёт тем же конвейером, что у
остальных уведомлений (лимитер, тихие часы, настройки S43, статус канала).
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final, NewType
from uuid import UUID

from app.modules.notifications.domain.catalog import BROADCAST_GROUPS, EventGroup
from app.modules.notifications.errors import BroadcastStateError
from app.platform.kernel.errors import DomainValidationError
from app.platform.kernel.ids import CityId, UserId
from app.platform.kernel.localized import Locale, LocalizedText

BroadcastId = NewType("BroadcastId", UUID)

MAX_TEXT: Final = 3500
"""Знаков в тексте одного языка: сообщение бота — до 4096, запас на экранирование `&`, `<`."""
SERBIAN: Final = frozenset({Locale.SR_LATN, Locale.SR_CYRL})
"""Текст нужен на русском и на сербском (любым алфавитом): читатель другого алфавита получает
его по цепочке §7.4 — кириллицу латиницей транслитом, латиницу как есть."""


class BroadcastStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    """Старт назначен на будущее: разбор аудитории начнётся в `starts_at`."""
    SENDING = "sending"
    """Сообщения встают в очередь и уходят; пока есть ждущие доставки — рассылка идёт."""
    DONE = "done"
    CANCELLED = "cancelled"


ACTIVE: Final = frozenset({BroadcastStatus.SCHEDULED, BroadcastStatus.SENDING})


class Audience(StrEnum):
    """Кому из тех, кто разрешил боту писать и включил группу рассылки."""

    ALL = "all"
    SPECIALISTS = "specialists"
    """С профилем исполнителя (любой статус, кроме удалённого)."""
    CLIENTS = "clients"
    """Без профиля исполнителя."""
    FOUNDING = "founding"
    """Founding-специалисты (§15.2): им — приглашение в лист ожидания Pro (Q24)."""


class BroadcastAction(StrEnum):
    """Кнопка действия под рассылкой (callback, platform/telegram/callbacks.py)."""

    PRO_WAITLIST = "pro_waitlist"
    """«Хочу узнать первым»: лист ожидания Pro (Q24), нажатие обрабатывает бот specialists."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Segment:
    """Чем аудитория отбирает получателя: профиль исполнителя и город."""

    is_specialist: bool
    is_founding: bool
    city_id: CityId | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Targeting:
    audience: Audience = Audience.ALL
    city_id: CityId | None = None
    """Только этот город: у исполнителя — город профиля, у клиента — домашний город."""

    def includes(self, segment: Segment) -> bool:
        if self.city_id is not None and segment.city_id != self.city_id:
            return False
        match self.audience:
            case Audience.ALL:
                return True
            case Audience.SPECIALISTS:
                return segment.is_specialist
            case Audience.CLIENTS:
                return not segment.is_specialist
            case Audience.FOUNDING:
                return segment.is_specialist and segment.is_founding


@dataclass(slots=True, kw_only=True)
class Broadcast:
    id: BroadcastId
    text: LocalizedText
    group: EventGroup
    targeting: Targeting = field(default_factory=Targeting)
    link: str | None = None
    """Код deep link кнопки «Открыть» (§11.4); проверяет use case кодеком ссылок."""
    action: BroadcastAction | None = None
    created_by: UserId
    created_at: datetime
    status: BroadcastStatus = BroadcastStatus.DRAFT
    starts_at: datetime | None = None
    finished_at: datetime | None = None
    cursor: UserId | None = None
    """Последний разобранный получатель (по id): разбор аудитории идёт пачками и после сбоя
    продолжается с места."""
    version: int = 0

    def __post_init__(self) -> None:
        if self.group not in BROADCAST_GROUPS:
            raise DomainValidationError(field="group", value=self.group.value)
        if Locale.RU not in self.text.values:
            raise DomainValidationError(field="text", reason="missing_locale", value="ru")
        if not SERBIAN & set(self.text.values):
            raise DomainValidationError(field="text", reason="missing_locale", value="sr")
        for locale, value in self.text.values.items():
            if len(value) > MAX_TEXT:
                raise DomainValidationError(field="text", reason="too_long", value=locale.value)
        if self.link is not None and self.action is not None:
            # в сообщении одна кнопка: и ссылка, и действие — уже выбор за человека
            raise DomainValidationError(field="action", reason="one_button")

    def start(self, now: datetime, at: datetime | None = None) -> None:
        """Начать сейчас или в `at`: дальше разбор аудитории задачей очереди."""
        self._require(BroadcastStatus.DRAFT, to="start")
        if at is not None and at > now:
            self.status, self.starts_at = BroadcastStatus.SCHEDULED, at
        else:
            self.status, self.starts_at = BroadcastStatus.SENDING, now

    def begin(self) -> bool:
        """Задача разбора пришла к сроку: запланированная рассылка идёт. False — её отменили."""
        if self.status is BroadcastStatus.SCHEDULED:
            self.status = BroadcastStatus.SENDING
        return self.status is BroadcastStatus.SENDING

    def advance(self, last: UserId) -> None:
        """Пачка получателей разобрана до `last` включительно."""
        self._require(BroadcastStatus.SENDING, to="advance")
        self.cursor = last

    def finish(self, now: datetime) -> bool:
        """Ждущих доставок нет: рассылка завершена. False — она уже не идёт."""
        if self.status is not BroadcastStatus.SENDING:
            return False
        self.status, self.finished_at = BroadcastStatus.DONE, now
        return True

    def cancel(self, now: datetime) -> None:
        if self.status not in {BroadcastStatus.DRAFT, *ACTIVE}:
            raise BroadcastStateError(broadcast_status=self.status.value, action="cancel")
        self.status, self.finished_at = BroadcastStatus.CANCELLED, now

    def _require(self, status: BroadcastStatus, *, to: str) -> None:
        if self.status is not status:
            raise BroadcastStateError(broadcast_status=self.status.value, action=to)


def dedupe_prefix(broadcast_id: BroadcastId) -> str:
    """Ключи уведомлений рассылки: отмена гасит ждущие доставки по этому префиксу."""
    return f"broadcast:{broadcast_id}:"
