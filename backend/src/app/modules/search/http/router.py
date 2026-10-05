"""HTTP search (DEVELOPMENT_PLAN 4.2, 4.3a, 4.6): выдача специалистов S05 с фильтрами шторки S06,
подсказки при вводе и избранное.

Каталог 🔓 открыт и гостю. Лимит — 60 запросов в минуту на адрес гостя и 120 на вошедшего
(ARCHITECTURE §13.3). Порядок, этапы поиска и пустая выдача — в use case. Избранное — только
вошедшему: «мои мастера» S12 и сердечко на S05 и S08; заявки — с шагом 5.3.
"""

from typing import Annotated, Literal
from uuid import UUID

import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, Response, status

from app.modules.search.application.dto import SpecialistFilters, ZeroResult
from app.modules.search.application.use_cases.add_favorite import (
    AddFavorite,
    AddFavoriteCommand,
)
from app.modules.search.application.use_cases.count_by_category import (
    CountByCategory,
    CountByCategoryCommand,
)
from app.modules.search.application.use_cases.count_specialists import (
    CountSpecialists,
    CountSpecialistsCommand,
)
from app.modules.search.application.use_cases.list_favorites import (
    ListFavorites,
    ListFavoritesCommand,
)
from app.modules.search.application.use_cases.remove_favorite import (
    RemoveFavorite,
    RemoveFavoriteCommand,
)
from app.modules.search.application.use_cases.search_specialists import (
    SearchSpecialists,
    SearchSpecialistsCommand,
)
from app.modules.search.application.use_cases.suggest_categories import (
    MAX_INPUT,
    SuggestCategories,
    SuggestCategoriesCommand,
)
from app.modules.search.domain.favorites import FavoriteType
from app.modules.search.domain.query import MAX_QUERY, SpecialistSort
from app.modules.search.http.schemas import (
    CategoryCountOut,
    CategoryCountsOut,
    FavoritesOut,
    SpecialistCardOut,
    SpecialistCountOut,
    SpecialistPageOut,
    SuggestOut,
)
from app.platform.http.fields import BIGINT_MAX, INT4_MAX, DistrictIdIn
from app.platform.http.pagination import PageParams
from app.platform.http.ratelimit import GuestOrUserRateLimit
from app.platform.http.security import AUTHENTICATED, optional_principal
from app.platform.kernel.errors import DomainValidationError
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CategoryId, CityId
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Principal
from app.platform.ratelimit import Rate

SEARCH_GUEST = Rate("search.guest", "60/minute")
SEARCH_USER = Rate("search.user", "120/minute")
SUGGEST_GUEST = Rate("search.suggest_guest", "60/minute")
SUGGEST_USER = Rate("search.suggest_user", "120/minute")
"""Свои счётчики: набор текста не съедает лимит выдачи."""
SUGGEST_MAX_AGE = 300
COUNTS_MAX_AGE = 300
METERS_IN_KM = 1000
MAX_LISTED = 20
"""Районов, языков, форматов в одном фильтре — больше в шторке не выбрать."""

log = structlog.get_logger(__name__)
router = APIRouter(tags=["search"])
FavoriteProfile = Annotated[UUID, Path(description="id профиля специалиста")]
Viewer = Annotated[Principal | None, Depends(optional_principal)]
search_limit = [Depends(GuestOrUserRateLimit(guest=SEARCH_GUEST, user=SEARCH_USER))]
suggest_limit = [Depends(GuestOrUserRateLimit(guest=SUGGEST_GUEST, user=SUGGEST_USER))]


def specialist_filters(
    *,
    city_id: Annotated[CityId, Query(ge=1, le=INT4_MAX, description="Город выдачи")],
    category_id: Annotated[
        CategoryId | None, Query(ge=1, le=INT4_MAX, description="С подкатегориями")
    ] = None,
    district_ids: Annotated[list[DistrictIdIn] | None, Query(max_length=MAX_LISTED)] = None,
    lat: Annotated[float | None, Query(ge=-90, le=90, description="Точка клиента")] = None,
    lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    radius_km: Annotated[int | None, Query(ge=1, le=50, description="Нужна точка")] = None,
    travels_to_me: Annotated[
        bool, Query(description="Выезжает к точке клиента (его радиус выезда)")
    ] = False,
    price_max: Annotated[
        int | None, Query(ge=0, le=BIGINT_MAX, description="Цена «до», пара")
    ] = None,
    rating_min: Annotated[float | None, Query(ge=1, le=5)] = None,
    languages: Annotated[
        list[str] | None, Query(max_length=MAX_LISTED, description="ru, sr, en, uk")
    ] = None,
    work_modes: Annotated[
        list[Literal["at_client", "at_own_place", "remote"]] | None,
        Query(max_length=MAX_LISTED),
    ] = None,
    available_today: Annotated[bool, Query()] = False,
    verified: Annotated[bool, Query(description="С подтверждённым телефоном (v1)")] = False,
    with_reviews: Annotated[bool, Query()] = False,
    kind: Annotated[
        Literal["pro", "casual"], Query(description="«Подработка» — только явно")
    ] = "pro",
) -> SpecialistFilters:
    if (lat is None) != (lon is None):
        raise DomainValidationError(field="lat" if lat is None else "lon", reason="pair")
    return SpecialistFilters(
        city_id=city_id,
        kind=kind,
        category_id=category_id,
        district_ids=tuple(district_ids or ()),
        point=GeoPoint(lat=lat, lon=lon) if lat is not None and lon is not None else None,
        radius_m=radius_km * METERS_IN_KM if radius_km else None,
        travels_to_me=travels_to_me,
        price_max=price_max,
        rating_min=rating_min,
        languages=tuple(languages or ()),
        work_modes=tuple(work_modes or ()),
        available_today=available_today,
        verified=verified,
        with_reviews=with_reviews,
    )


@router.get("/specialists", response_model=SpecialistPageOut, dependencies=search_limit)
@inject
async def list_specialists(
    *,
    response: Response,
    background: BackgroundTasks,
    search: FromDishka[SearchSpecialists],
    locale: FromDishka[Locale],
    filters: Annotated[SpecialistFilters, Depends(specialist_filters)],
    page: PageParams,
    viewer: Viewer,
    q: Annotated[
        str | None, Query(max_length=2 * MAX_QUERY, description="Текст: ru, sr, en, с опечатками")
    ] = None,
    sort: Annotated[
        SpecialistSort, Query(description="distance — нужна точка клиента")
    ] = SpecialistSort.RELEVANCE,
    urgent: Annotated[bool, Query(description="«Срочно»: доступные сегодня — выше")] = False,
) -> SpecialistPageOut:
    """Выдача специалистов: текст, фильтры, порядок; карточки готовы к показу. Вошедшему — без
    тех, с кем у него блокировка (4.7)."""
    results = await search(
        SearchSpecialistsCommand(
            filters=filters,
            q=q,
            sort=sort,
            page=page,
            locale=locale.value,
            urgent=urgent,
            viewer_id=viewer.user_id if viewer is not None else None,
        )
    )
    if results.zero_result is not None:
        # журнал пустых выдач — после ответа: клиент не ждёт INSERT и COMMIT
        background.add_task(_record_zero_result, search, results.zero_result)
    response.headers["Vary"] = "Accept-Language"
    return SpecialistPageOut.from_results(results, locale)


async def _record_zero_result(search: SearchSpecialists, entry: ZeroResult) -> None:
    """Журнал — материал для словаря, не часть ответа: сбой только пишется в лог."""
    try:
        await search.record(entry)
    except Exception as exc:  # noqa: BLE001 — потерянная запись журнала не ошибка запроса
        log.warning("zero_result_not_logged", error=type(exc).__name__)


@router.get("/suggest", response_model=SuggestOut, dependencies=suggest_limit)
@inject
async def suggest(
    *,
    response: Response,
    suggest: FromDishka[SuggestCategories],
    locale: FromDishka[Locale],
    q: Annotated[str, Query(min_length=1, max_length=MAX_INPUT, description="Что набрано")],
) -> SuggestOut:
    """Подсказки при вводе: до 8 категорий по началу слова, затем похожие (опечатки)."""
    found = await suggest(SuggestCategoriesCommand(q=q))
    response.headers["Vary"] = "Accept-Language"
    response.headers["Cache-Control"] = f"private, max-age={SUGGEST_MAX_AGE}"
    return SuggestOut.of(found, locale)


@router.get("/specialists/count", response_model=SpecialistCountOut, dependencies=search_limit)
@inject
async def count_specialists(
    *,
    count: FromDishka[CountSpecialists],
    filters: Annotated[SpecialistFilters, Depends(specialist_filters)],
    viewer: Viewer,
    q: Annotated[str | None, Query(max_length=2 * MAX_QUERY)] = None,
) -> SpecialistCountOut:
    """Сколько специалистов покажет выдача с этими фильтрами: «Показать N» в шторке S06."""
    found = await count(
        CountSpecialistsCommand(
            filters=filters, q=q, viewer_id=viewer.user_id if viewer is not None else None
        )
    )
    return SpecialistCountOut(count=found.count, capped=found.capped)


@router.get("/specialists/by-category", response_model=CategoryCountsOut, dependencies=search_limit)
@inject
async def count_by_category(
    *,
    response: Response,
    counts: FromDishka[CountByCategory],
    city_id: Annotated[CityId, Query(ge=1, le=INT4_MAX)],
    kind: Annotated[Literal["pro", "casual"], Query()] = "pro",
) -> CategoryCountsOut:
    """Сколько специалистов в каждой категории города — для дерева S04 (с подкатегориями)."""
    found = await counts(CountByCategoryCommand(city_id=city_id, kind=kind))
    response.headers["Cache-Control"] = f"private, max-age={COUNTS_MAX_AGE}"
    return CategoryCountsOut(
        items=[
            CategoryCountOut(category_id=category_id, count=number)
            for category_id, number in sorted(found.items())
        ]
    )


@router.get("/me/favorites", response_model=FavoritesOut, dependencies=AUTHENTICATED)
@inject
async def list_favorites(
    *,
    response: Response,
    principal: FromDishka[Principal],
    favorites: FromDishka[ListFavorites],
    locale: FromDishka[Locale],
) -> FavoritesOut:
    """Избранные специалисты S12: те, кто виден в каталоге, новые первыми. Сохранённые заявки —
    `GET /me/favorites/jobs` (модуль jobs, 5.3)."""
    cards = await favorites(ListFavoritesCommand(actor_id=principal.user_id))
    response.headers["Vary"] = "Accept-Language"
    return FavoritesOut(items=[SpecialistCardOut.of(card, locale) for card in cards])


@router.put(
    "/me/favorites/profile/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=AUTHENTICATED,
)
@inject
async def add_favorite(
    *, profile_id: FavoriteProfile, principal: FromDishka[Principal], add: FromDishka[AddFavorite]
) -> None:
    """Специалист — в избранное (сердечко S05, S08). Повтор — без ошибки; профиль, которого нет
    в каталоге, — 404; больше 100 — `favorites_full`."""
    await add(
        AddFavoriteCommand(
            actor_id=principal.user_id, target_type=FavoriteType.PROFILE, target_id=profile_id
        )
    )


@router.delete(
    "/me/favorites/profile/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=AUTHENTICATED,
)
@inject
async def remove_favorite(
    *,
    profile_id: FavoriteProfile,
    principal: FromDishka[Principal],
    remove: FromDishka[RemoveFavorite],
) -> None:
    """Убрать специалиста из избранного; чего нет — без ошибки."""
    await remove(
        RemoveFavoriteCommand(
            actor_id=principal.user_id, target_type=FavoriteType.PROFILE, target_id=profile_id
        )
    )
