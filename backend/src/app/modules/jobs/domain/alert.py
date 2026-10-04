"""Подписка на новые заявки (DEVELOPMENT_PLAN 5.7; ARCHITECTURE §7.3, §9.6): «присылай заявки по
электрике в Лимане от 3 000 RSD» — S18, S19 и карточка заявки в боте B1.

Что подходит: категории (выбранные узлы дерева — заявка подходит, если её услуга или любой её
предок среди них: у заявки есть путь от корня, поэтому новая подкатегория раздела попадёт в
подписку без правки), город, районы или точка с радиусом (ни того ни другого — весь город),
бюджет «от», срочности, языки общения. Как присылать — сразу или подборкой раз в день. Подписку
можно выключить (переключатель S18) и поставить на паузу (кнопка B1, `/alerts` в боте): пауза
кончается сама.
"""

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum
from typing import Final, NewType
from uuid import UUID

from app.modules.jobs.domain.job import MAX_BUDGET, Urgency
from app.modules.jobs.errors import InvalidAlertError
from app.platform.kernel.clock import BUSINESS_TZ
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, UserId

AlertId = NewType("AlertId", UUID)

MAX_ALERTS: Final = 10
"""Подписок у исполнителя: точные подписки лучше одной «на всё» (§11.2, скорость рассылки)."""
MAX_ALERT_CATEGORIES: Final = 20
MAX_ALERT_DISTRICTS: Final = 30
MAX_ALERT_LANGUAGES: Final = 5
MIN_RADIUS_M: Final = 500
MAX_RADIUS_M: Final = 30_000
"""Потолок радиуса (§7.3): с ним индекс по центру участвует в плане матчинга."""
WEEK_PAUSE: Final = timedelta(days=7)
_LANGUAGE: Final = re.compile(r"[a-z]{2,3}(-[A-Za-z]{2,4})?")


class AlertDelivery(StrEnum):
    INSTANT = "instant"
    """Карточка B1 сразу после публикации заявки."""
    DIGEST = "digest"
    """Подборка раз в день — в час дайджеста получателя (настройки уведомлений, 09:00)."""


class PauseSpan(StrEnum):
    """Пауза из бота: до конца сегодняшнего дня по Белграду или на неделю."""

    TODAY = "today"
    WEEK = "week"


def pause_end(now: datetime, span: PauseSpan) -> datetime:
    """Когда пауза кончится сама: «на сегодня» — в полночь по Белграду, «на неделю» — через 7
    дней от нажатия."""
    if span is PauseSpan.WEEK:
        return now + WEEK_PAUSE
    tomorrow = now.astimezone(BUSINESS_TZ).date() + timedelta(days=1)
    return datetime.combine(tomorrow, time(0, 0), tzinfo=BUSINESS_TZ)


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertCriteria:
    """Что подходит подписке. Районы и точка с радиусом взаимоисключающие: ни того ни другого —
    весь город."""

    category_ids: tuple[CategoryId, ...]
    city_id: CityId
    district_ids: tuple[DistrictId, ...] = ()
    center: GeoPoint | None = None
    radius_m: int | None = None
    min_budget: int | None = None
    """Пара: бюджет заявки (верх диапазона или фикс) не меньше; договорные подходят — о цене
    договорятся в отклике."""
    urgencies: tuple[Urgency, ...] = ()
    """Пусто — любые."""
    languages: tuple[str, ...] = ()
    """Пусто — любые; заявки без языка подходят всем (как в ленте 5.3)."""

    def __post_init__(self) -> None:
        categories = tuple(dict.fromkeys(self.category_ids))
        if not 1 <= len(categories) <= MAX_ALERT_CATEGORIES:
            raise InvalidAlertError(field="category_ids", reason="count")
        districts = tuple(dict.fromkeys(self.district_ids))
        if len(districts) > MAX_ALERT_DISTRICTS:
            raise InvalidAlertError(field="district_ids", reason="count")
        if (self.center is None) != (self.radius_m is None):
            raise InvalidAlertError(field="radius_m", reason="needs_center")
        if self.radius_m is not None and not MIN_RADIUS_M <= self.radius_m <= MAX_RADIUS_M:
            raise InvalidAlertError(field="radius_m", reason="out_of_range")
        if districts and self.center is not None:
            raise InvalidAlertError(field="district_ids", reason="districts_or_radius")
        if self.min_budget is not None and not 0 < self.min_budget <= MAX_BUDGET:
            raise InvalidAlertError(field="min_budget", reason="out_of_range")
        languages = tuple(dict.fromkeys(self.languages))
        if len(languages) > MAX_ALERT_LANGUAGES or any(
            _LANGUAGE.fullmatch(code) is None for code in languages
        ):
            raise InvalidAlertError(field="languages", reason="invalid")
        object.__setattr__(self, "category_ids", categories)
        object.__setattr__(self, "district_ids", districts)
        object.__setattr__(self, "urgencies", tuple(dict.fromkeys(self.urgencies)))
        object.__setattr__(self, "languages", languages)


@dataclass(frozen=True, slots=True, kw_only=True)
class JobAlert:
    id: AlertId
    user_id: UserId
    criteria: AlertCriteria
    delivery: AlertDelivery
    is_active: bool
    """Переключатель S18: выключенная не присылает ничего, пока её не включат."""
    paused_until: datetime | None
    """Пауза из бота: до этого момента не присылает; позже — снова как обычно."""
    created_at: datetime
    updated_at: datetime

    def paused(self, now: datetime) -> bool:
        return self.paused_until is not None and self.paused_until > now

    def receives(self, now: datetime) -> bool:
        """Присылает ли она заявки сейчас: включена и не на паузе."""
        return self.is_active and not self.paused(now)
