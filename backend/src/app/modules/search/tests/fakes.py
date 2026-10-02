"""Фейки портов и фасадов для тестов search (ADR-0020 §11)."""

import json
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import TracebackType
from typing import Self
from uuid import UUID

from app.modules.catalog.api import CategorySuggestion, CategorySummary, SearchTerm, TermMatch
from app.modules.media.api import MediaRef
from app.modules.search.application.dto import (
    SpecialistFilters,
    SpecialistHit,
    TextMatch,
    ZeroResult,
    ZeroResultStat,
)
from app.modules.search.domain.favorites import FavoriteType
from app.modules.search.domain.query import RankWeights, SpecialistSort, Stage
from app.platform.kernel.aggregate import AggregateRoot
from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import CategoryId, CityId, MediaId, UserId


@dataclass(frozen=True, slots=True)
class SearchCall:
    match: TextMatch | None
    sort: SpecialistSort
    weights: RankWeights
    offset: int
    limit: int

    @property
    def stage(self) -> Stage:
        return self.match.stage if self.match is not None else Stage.BROWSE


@dataclass
class FakeSearch:
    """SpecialistSearch: строки по этапам; помнит, какие этапы и страницы спрашивали."""

    by_stage: dict[Stage, list[SpecialistHit]] = field(default_factory=dict)
    calls: list[SearchCall] = field(default_factory=list)
    counted: list[Stage] = field(default_factory=list)
    categories: dict[CategoryId, int] = field(default_factory=dict)
    counted_categories: list[tuple[CityId, str]] = field(default_factory=list)
    visible: dict[UUID, SpecialistHit] = field(default_factory=dict)
    """Строки, видимые в каталоге: `listed` (избранное)."""

    async def search(
        self,
        filters: SpecialistFilters,
        match: TextMatch | None,
        *,
        sort: SpecialistSort,
        weights: RankWeights,
        offset: int,
        limit: int,
        now: datetime,
    ) -> list[SpecialistHit]:
        call = SearchCall(match=match, sort=sort, weights=weights, offset=offset, limit=limit)
        self.calls.append(call)
        return self.by_stage.get(call.stage, [])[offset : offset + limit]

    async def count(
        self,
        filters: SpecialistFilters,
        match: TextMatch | None,
        *,
        now: datetime,
        cap: int,
    ) -> int:
        stage = match.stage if match is not None else Stage.BROWSE
        self.counted.append(stage)
        return min(len(self.by_stage.get(stage, [])), cap)

    async def count_by_category(self, city_id: CityId, kind: str) -> dict[CategoryId, int]:
        self.counted_categories.append((city_id, kind))
        return dict(self.categories)

    async def listed(self, profile_ids: Collection[UUID]) -> list[SpecialistHit]:
        return [self.visible[i] for i in profile_ids if i in self.visible]


@dataclass
class FakeFavorites:
    """Favorites: записи по порядку добавления; `ids` — новые первыми."""

    rows: list[tuple[UserId, FavoriteType, UUID]] = field(default_factory=list)

    async def add(self, user_id: UserId, target_type: FavoriteType, target_id: UUID) -> bool:
        if (user_id, target_type, target_id) in self.rows:
            return False
        self.rows.append((user_id, target_type, target_id))
        return True

    async def remove(self, user_id: UserId, target_type: FavoriteType, target_id: UUID) -> None:
        if (user_id, target_type, target_id) in self.rows:
            self.rows.remove((user_id, target_type, target_id))

    async def count(self, user_id: UserId, target_type: FavoriteType) -> int:
        return len(await self.ids(user_id, target_type))

    async def ids(self, user_id: UserId, target_type: FavoriteType) -> list[UUID]:
        return [t for u, k, t in reversed(self.rows) if (u, k) == (user_id, target_type)]

    async def forget(self, user_id: UserId) -> None:
        self.rows = [row for row in self.rows if row[0] != user_id]


@dataclass
class FakeCatalog:
    """CatalogApi: словарь поиска — запрос целиком → совпадение."""

    matches: dict[str, TermMatch] = field(default_factory=dict)
    similar: dict[str, TermMatch] = field(default_factory=dict)
    suggestions: dict[str, list[CategorySuggestion]] = field(default_factory=dict)
    suggested: list[tuple[str, int]] = field(default_factory=list)

    async def category(self, category_id: CategoryId) -> CategorySummary | None:
        raise NotImplementedError

    async def categories(self, category_ids: Collection[CategoryId]) -> list[CategorySummary]:
        raise NotImplementedError

    async def search_terms(
        self, category_ids: Collection[CategoryId]
    ) -> dict[CategoryId, tuple[SearchTerm, ...]]:
        raise NotImplementedError

    async def match_query(self, text: str) -> TermMatch | None:
        return self.matches.get(text)

    async def similar_term(self, text: str) -> TermMatch | None:
        return self.similar.get(text)

    async def suggest(self, text: str, *, limit: int) -> list[CategorySuggestion]:
        self.suggested.append((text, limit))
        return self.suggestions.get(text, [])[:limit]


@dataclass
class FakeMedia:
    """MediaApi: как показать файлы — для фото профиля в карточке."""

    files: dict[MediaId, MediaRef] = field(default_factory=dict)
    asked: list[frozenset[MediaId]] = field(default_factory=list)

    async def owned(self, owner_id: UserId, media_id: MediaId, *, purpose: str) -> MediaRef:
        raise NotImplementedError

    async def refs(self, media_ids: Collection[MediaId]) -> dict[MediaId, MediaRef]:
        self.asked.append(frozenset(media_ids))
        return {media_id: self.files[media_id] for media_id in media_ids if media_id in self.files}

    async def discard(self, owner_id: UserId, media_id: MediaId) -> None:
        raise NotImplementedError

    async def held(self, media_ids: Collection[MediaId]) -> frozenset[MediaId]:
        raise NotImplementedError


@dataclass
class FakeFlags:
    values: dict[str, object] = field(default_factory=dict)

    async def is_enabled(self, key: str) -> bool:
        return key in self.values

    async def value(self, key: str) -> object | None:
        return self.values.get(key)


@dataclass
class FakeLog:
    entries: list[ZeroResult] = field(default_factory=list)
    reported: list[tuple[datetime, int]] = field(default_factory=list)

    async def record(self, entry: ZeroResult) -> None:
        self.entries.append(entry)

    async def zero_results(self, since: datetime, *, limit: int) -> list[ZeroResultStat]:
        self.reported.append((since, limit))
        return []


class FakeUoW:
    """UnitOfWork без базы: считает завершённые блоки."""

    def __init__(self) -> None:
        self.active = False
        self.committed = 0

    async def __aenter__(self) -> Self:
        self.active = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.active = False
        if exc is None:
            self.committed += 1

    def track(self, aggregate: AggregateRoot) -> None:
        raise NotImplementedError

    def add_event(self, event: DomainEvent) -> None:
        raise NotImplementedError

    def require_active(self) -> None:
        assert self.active, "no active UnitOfWork"


@dataclass
class FakeCache:
    """JsonCache в памяти: значения проходят через JSON, как в Valkey."""

    values: dict[str, str] = field(default_factory=dict)
    ttls: dict[str, timedelta] = field(default_factory=dict)

    async def get(self, key: str) -> object | None:
        raw = self.values.get(key)
        return json.loads(raw) if raw is not None else None

    async def set(self, key: str, value: object, *, ttl: timedelta) -> None:
        self.values[key] = json.dumps(value)
        self.ttls[key] = ttl
