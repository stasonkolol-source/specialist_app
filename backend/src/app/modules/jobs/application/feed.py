"""Лента заявок для исполнителей (экраны S13–S15, DEVELOPMENT_PLAN 5.3; ARCHITECTURE §9.6).

Опубликованные публичные заявки города, свежие сверху, keyset по `(published_at, id)`. Фильтры —
категории (с подкатегориями), районы или радиус от точки, срочность, бюджет «от», язык общения,
«только с фото»; «по моим подпискам» (`feed=alerts`, 5.7) — заявки, которые подходят хотя бы
одной включённой подписке зрителя (то же правило, что матчинг §9.6). Свои заявки, скрытые («не
подходит») и заявки тех, с кем у зрителя блокировка (4.7), ему не показываются. Имена категорий
и районов клиент берёт из справочников (они у него уже есть): в карточке — только id.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from app.modules.jobs.domain.job import BudgetType, BudgetUnit, JobId, Urgency
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, MediaId, UserId

CARD_PHOTOS: Final = 3
"""Фото в карточке ленты: превью, остальные — на S15."""
DESCRIPTION_PREVIEW: Final = 280
"""Начало описания в карточке: две-три строки на экране, остальное — на S15."""


@dataclass(frozen=True, slots=True, kw_only=True)
class FeedFilters:
    city_id: CityId | None
    """Город ленты; None — только с `alerts_of` (`/feed` бота): город задают подписки."""
    category_ids: tuple[CategoryId, ...] = ()
    """Любая из категорий или их подкатегорий."""
    district_ids: tuple[DistrictId, ...] = ()
    near: GeoPoint | None = None
    """Точка зрителя: расстояние в карточке и центр радиуса."""
    radius_m: int | None = None
    urgencies: tuple[Urgency, ...] = ()
    budget_from: int | None = None
    """Пара: бюджет (верх диапазона или фикс) не меньше; договорные — не подходят."""
    languages: tuple[str, ...] = ()
    """Язык общения: заявки на любом из них и без указанного языка."""
    with_photos: bool = False
    published_after: datetime | None = None
    """«Новые»: опубликованные позже — счётчик на Главной."""
    hidden_clients: tuple[UserId, ...] = ()
    """С кем у зрителя блокировка в любую сторону (4.7): их заявок нет. Ставит use case по
    зрителю, не фильтры шторки."""
    alerts_of: UserId | None = None
    """«По моим подпискам» (5.7): только заявки, подходящие включённой подписке этого человека."""


@dataclass(frozen=True, slots=True, kw_only=True)
class FeedItem:
    """Строка ленты, как её читает запрос."""

    id: JobId
    title: str
    description: str
    category_id: CategoryId
    urgency: Urgency
    preferred_from: datetime | None
    preferred_to: datetime | None
    budget_type: BudgetType
    budget_min: int | None
    budget_max: int | None
    budget_unit: BudgetUnit
    district_id: DistrictId | None
    distance_m: int | None
    """До точки зрителя, если она известна, — уже округлено."""
    media_ids: tuple[MediaId, ...]
    """Первые фото по порядку."""
    photos_count: int
    responses_count: int
    max_responses: int
    published_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class Photo:
    """Превью фото заявки: вариант thumb и ThumbHash."""

    url: str
    width: int
    height: int
    placeholder: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class JobCard:
    item: FeedItem
    photos: tuple[Photo, ...]
