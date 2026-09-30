"""Настройки уведомлений пользователя (S43, ARCHITECTURE §11.2): группы × каналы, тихие часы.

Выбор хранится только там, где человек что-то менял: остальное — умолчания, и новая группа
или канал не требуют миграции данных. По умолчанию всё включено, кроме новостей (opt-in);
служебную группу выключить нельзя. Тихие часы — по времени Сербии (Europe/Belgrade): в
MVP все пользователи там, а часового пояса человека мы не знаем.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from types import MappingProxyType
from zoneinfo import ZoneInfo

from app.modules.notifications.domain.catalog import (
    MANDATORY_GROUPS,
    OPT_IN_GROUPS,
    Channel,
    EventGroup,
)
from app.modules.notifications.errors import MandatoryGroupError
from app.platform.kernel.errors import DomainValidationError

TIMEZONE = ZoneInfo("Europe/Belgrade")
QUIET_START = time(22, 0)
QUIET_END = time(8, 0)
DIGEST_HOUR = 9


@dataclass(frozen=True, slots=True, kw_only=True)
class QuietHours:
    """Окно, в которое бот не пишет (кроме срочного); может переходить через полночь."""

    enabled: bool = True
    start: time = QUIET_START
    end: time = QUIET_END

    def __post_init__(self) -> None:
        if self.start == self.end:
            raise DomainValidationError(field="quiet_hours", value=self.start.isoformat())
        if self.start.tzinfo is not None or self.end.tzinfo is not None:
            raise DomainValidationError(field="quiet_hours", reason="local time expected")

    def release_at(self, now: datetime) -> datetime:
        """Когда доставить уведомление, созданное в `now`: сразу или в конце тихих часов."""
        if not self.enabled:
            return now
        local = now.astimezone(TIMEZONE)
        clock = local.time().replace(tzinfo=None)
        if self.start < self.end:  # окно внутри суток: 01:00–06:00
            if not self.start <= clock < self.end:
                return now
            day = local.date()
        elif clock >= self.start:  # через полночь, вечерняя часть: 22:00–24:00
            day = local.date() + timedelta(days=1)
        elif clock < self.end:  # утренняя часть: 00:00–08:00
            day = local.date()
        else:
            return now
        # время по часам Белграда в день выхода: переход на летнее время учитывает zoneinfo
        return datetime.combine(day, self.end, tzinfo=TIMEZONE).astimezone(UTC)


@dataclass(frozen=True, slots=True)
class Preferences:
    """Выбор пользователя «группа × канал»; чего нет — умолчание. Хранит только отличия от
    умолчаний: одинаковые по смыслу настройки равны."""

    choices: Mapping[tuple[EventGroup, Channel], bool] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        for (group, _channel), enabled in self.choices.items():
            if group in MANDATORY_GROUPS and not enabled:
                raise MandatoryGroupError(group=group.value)
        object.__setattr__(self, "choices", MappingProxyType(self.overrides()))

    def allows(self, group: EventGroup, channel: Channel) -> bool:
        if group in MANDATORY_GROUPS:
            return True
        return self.choices.get((group, channel), default_for(group))

    def overrides(self) -> dict[tuple[EventGroup, Channel], bool]:
        """Выбор, отличный от умолчаний: только он хранится."""
        return {
            (group, channel): enabled
            for (group, channel), enabled in self.choices.items()
            if group not in MANDATORY_GROUPS and enabled != default_for(group)
        }


def default_for(group: EventGroup) -> bool:
    """Включена ли группа, пока человек её не трогал: всё, кроме opt-in."""
    return group not in OPT_IN_GROUPS


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationSettings:
    preferences: Preferences = field(default_factory=Preferences)
    quiet_hours: QuietHours = field(default_factory=QuietHours)
    digest_hour: int = DIGEST_HOUR
    """Час дайджеста подходящих заявок (0–23, по Белграду); дайджесты — шаг 3.x."""

    def __post_init__(self) -> None:
        if not 0 <= self.digest_hour <= 23:
            raise DomainValidationError(field="digest_hour", value=self.digest_hour)
