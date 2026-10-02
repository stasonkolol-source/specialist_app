"""Выдача специалистов (DEVELOPMENT_PLAN 4.2; ARCHITECTURE §9.2–9.5).

Без текста — фильтры и порядок. С текстом этапы идут по очереди до первой непустой выдачи:
1. запрос узнан в словаре категорий целиком или по началу — выдача этих категорий;
2. FTS по документу: все слова → по началу слов → любое слово (и имя по триграммам);
3. ближайшее слово словаря — «Возможно, вы имели в виду…».
Нечёткое совпадение — последним: имя мастера или редкое слово прайса FTS находит точнее,
чем похожая категория. Следующие страницы берутся тем же этапом — он записан в курсоре.
Пустая выдача с текстом пишется в журнал для словаря; ответ подсказывает, что делать.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from app.modules.catalog.api import CatalogApi
from app.modules.media.api import MediaApi, MediaRef
from app.modules.search.application.dto import (
    Avatar,
    SpecialistCard,
    SpecialistFilters,
    SpecialistHit,
    SpecialistResults,
    TextMatch,
    ZeroResult,
)
from app.modules.search.application.ports import QueryLog, SpecialistSearch
from app.modules.search.application.stages import QueryStages
from app.modules.search.domain.query import (
    MAX_OFFSET,
    NEW_UNTIL_REVIEWS,
    WEIGHTS_FLAG,
    PageCursor,
    QueryText,
    RankWeights,
    SpecialistSort,
    Stage,
    rounded_distance,
)
from app.platform.config.port import FeatureFlags
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.errors import DomainValidationError
from app.platform.kernel.ids import MediaId
from app.platform.kernel.pagination import Page, PageRequest

AVATAR_VARIANT: Final = "thumb"
"""320 px — карточка выдачи."""
READY = "ready"
RELAX_FILTERS: Final = "relax_filters"
POST_JOB: Final = "post_job"


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchSpecialistsCommand:
    filters: SpecialistFilters
    q: str | None = None
    sort: SpecialistSort = SpecialistSort.RELEVANCE
    page: PageRequest = field(default_factory=PageRequest)
    locale: str = "ru"
    """Язык интерфейса — только для журнала запросов без результатов."""
    urgent: bool = False
    """«Срочно» (чип S03): доступные сегодня — выше (§9.4). Без него доступность в балл не
    входит: иначе она перебивала бы совпадение с текстом запроса."""


class SearchSpecialists:
    def __init__(
        self,
        search: SpecialistSearch,
        catalog: CatalogApi,
        media: MediaApi,
        flags: FeatureFlags,
        log: QueryLog,
        uow: UnitOfWork,
        clock: Clock,
    ) -> None:
        self._search, self._stages, self._media = search, QueryStages(catalog), media
        self._flags, self._log, self._uow, self._clock = flags, log, uow, clock

    async def __call__(self, cmd: SearchSpecialistsCommand) -> SpecialistResults:
        _check(cmd)
        cursor = PageCursor.decode(cmd.page.cursor) if cmd.page.cursor else None
        offset = cursor.offset if cursor is not None else 0
        weights = RankWeights.from_flag(await self._flags.value(WEIGHTS_FLAG))
        if not cmd.urgent:
            weights = replace(weights, availability=0.0)
        now = self._clock.now()
        text = QueryText.parse(cmd.q)
        suggested: str | None = None
        async for match, suggestion in self._stages(text, cursor.stage if cursor else None):
            hits = await self._search.search(
                cmd.filters,
                match,
                sort=cmd.sort,
                weights=weights,
                offset=offset,
                limit=cmd.page.limit + 1,
                now=now,
            )
            if hits or cursor is not None:
                return await self._results(cmd, match, suggestion, hits, offset, now)
            suggested = suggestion or suggested
        if text is not None and cursor is None:
            await self._record(cmd, text, suggested)
        hints = (RELAX_FILTERS, POST_JOB) if cmd.filters.narrowed else (POST_JOB,)
        stage = Stage.BROWSE if text is None else Stage.ANY_WORD
        return SpecialistResults(page=Page(items=()), stage=stage, hints=hints)

    async def _results(
        self,
        cmd: SearchSpecialistsCommand,
        match: TextMatch | None,
        suggestion: str | None,
        hits: list[SpecialistHit],
        offset: int,
        now: datetime,
    ) -> SpecialistResults:
        limit = cmd.page.limit
        stage = match.stage if match is not None else Stage.BROWSE
        more = len(hits) > limit and offset + limit <= MAX_OFFSET
        shown = hits[:limit]
        wanted = {media for hit in shown if (media := _avatar_id(hit.card)) is not None}
        refs = await self._media.refs(wanted) if wanted else {}
        recognized = match.category_ids if match is not None else ()
        return SpecialistResults(
            page=Page(
                items=tuple(_card(hit, refs, now) for hit in shown),
                next_cursor=PageCursor(stage, offset + limit).encode() if more else None,
            ),
            stage=stage,
            category_ids=recognized,
            did_you_mean=suggestion,
        )

    async def _record(
        self, cmd: SearchSpecialistsCommand, text: QueryText, suggested: str | None
    ) -> None:
        filters = cmd.filters
        entry = ZeroResult(
            q=text.raw,
            locale=cmd.locale,
            city_id=filters.city_id,
            category_id=filters.category_id,
            filters=_chosen(filters),
            did_you_mean=suggested,
        )
        async with self._uow:
            await self._log.record(entry)


def _check(cmd: SearchSpecialistsCommand) -> None:
    """Расстояние, радиус и «выезжает ко мне» считаются от точки клиента — без неё нельзя."""
    filters = cmd.filters
    if filters.missing_point or (filters.point is None and cmd.sort is SpecialistSort.DISTANCE):
        raise DomainValidationError(field="lat", reason="point_required")


def _chosen(filters: SpecialistFilters) -> tuple[str, ...]:
    flags = {
        "district_ids": bool(filters.district_ids),
        "radius": bool(filters.radius_m),
        "travels_to_me": filters.travels_to_me,
        "price_max": filters.price_max is not None,
        "rating_min": filters.rating_min is not None,
        "languages": bool(filters.languages),
        "work_modes": bool(filters.work_modes),
        "available_today": filters.available_today,
        "verified": filters.verified,
        "with_reviews": filters.with_reviews,
    }
    return tuple(name for name, chosen in flags.items() if chosen)


def _avatar_id(card: Mapping[str, Any]) -> MediaId | None:
    avatar = card.get("avatar")
    return MediaId(UUID(avatar["media_id"])) if avatar else None


def _avatar(card: Mapping[str, Any], refs: Mapping[MediaId, MediaRef]) -> Avatar | None:
    media_id = _avatar_id(card)
    ref = refs.get(media_id) if media_id is not None else None
    if ref is None or ref.status != READY:
        return None
    variant = next((v for v in ref.variants if v.name == AVATAR_VARIANT), None)
    if variant is None:
        return None
    return Avatar(
        url=variant.url, width=variant.width, height=variant.height, placeholder=ref.placeholder
    )


def _card(hit: SpecialistHit, refs: Mapping[MediaId, MediaRef], now: datetime) -> SpecialistCard:
    card = hit.card
    district = card.get("district") or {}
    is_new = hit.rating_count < NEW_UNTIL_REVIEWS
    available = hit.available_until
    return SpecialistCard(
        profile_id=hit.profile_id,
        display_name=card["display_name"],
        headline=card.get("headline"),
        kind=card["kind"],
        avatar=_avatar(card, refs),
        district_id=district.get("id"),
        district_name=district.get("name") or {},
        distance_m=rounded_distance(hit.distance_m),
        languages=tuple(card.get("languages") or ()),
        category_ids=tuple(card.get("category_ids") or ()),
        price_from=hit.price_from,
        negotiable=bool(card.get("negotiable")) and hit.price_from is None,
        rating=None if is_new else hit.rating_bayes,
        rating_count=hit.rating_count,
        is_new=is_new,
        available_until=available if available is not None and available > now else None,
        badges=hit.badges,
    )
