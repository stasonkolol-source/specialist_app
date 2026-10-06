"""Сборка строк read-model из фасадов модулей ниже по DAG (ADR-0020 §5: чужие схемы не
читаем). Пачка профилей — несколько запросов на всю пачку, а не на каждый профиль.

Профиль попадает в индекс, только если он опубликован, а его автор не удалён и не скрыт
санкцией (приостановка, бан, теневой бан). Остальные строки удаляются; у срочной санкции
известен её конец — тогда профиль надо пересобрать снова (`reindex_at`).
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.catalog.api import CatalogApi, CategorySummary, SearchTerm
from app.modules.geo.api import DistrictSummary, GeoApi
from app.modules.identity.api import IdentityApi
from app.modules.media.api import MediaApi, MediaRef
from app.modules.pricing.api import PricingApi, SearchPrices
from app.modules.reviews.api import NO_REVIEWS_LOWER_BOUND, RatingSummary, ReviewsApi
from app.modules.search.domain.index import (
    IndexEntry,
    Labels,
    SearchDocument,
    activity_score,
    base_score,
    category_price_units,
    category_prices,
    serbian,
    with_ancestors,
)
from app.modules.specialists.api import ProfileForIndex, SpecialistsApi
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import CategoryId, DistrictId, MediaId

PUBLISHED = "published"
METERS_IN_KM = 1000
_LANG_GROUPS = {"ru": ("ru",), "sr": ("sr-Latn", "sr-Cyrl"), "en": ("en",)}


@dataclass(slots=True)
class Projection:
    entries: list[IndexEntry] = field(default_factory=list)
    removed: list[UUID] = field(default_factory=list)
    """Профили, которых в индексе быть не должно (нет, не опубликован, автор скрыт)."""
    reindex_at: dict[datetime, list[UUID]] = field(default_factory=dict)
    """Когда пересобрать снова: конец срочной санкции автора."""


class SpecialistProjection:
    def __init__(
        self,
        specialists: SpecialistsApi,
        identity: IdentityApi,
        pricing: PricingApi,
        catalog: CatalogApi,
        geo: GeoApi,
        media: MediaApi,
        reviews: ReviewsApi,
        clock: Clock,
    ) -> None:
        self._specialists, self._identity, self._pricing = specialists, identity, pricing
        self._catalog, self._geo, self._media, self._clock = catalog, geo, media, clock
        self._reviews = reviews

    async def build(self, profile_ids: Collection[UUID]) -> Projection:
        result = Projection()
        found = {p.id: p for p in await self._specialists.profiles_for_index(profile_ids)}
        published = [p for p in found.values() if p.status == PUBLISHED]
        hidden = await self._identity.hidden_from_search({p.user_id for p in published})
        visible: list[ProfileForIndex] = []
        for profile in published:
            if profile.user_id in hidden:
                until = hidden[profile.user_id]
                if until is not None:
                    result.reindex_at.setdefault(until, []).append(profile.id)
            else:
                visible.append(profile)
        shown = {p.id for p in visible}
        result.removed = [profile_id for profile_id in profile_ids if profile_id not in shown]
        if visible:
            context = await self._context(visible)
            result.entries = [self._entry(profile, context) for profile in visible]
        return result

    async def _context(self, profiles: list[ProfileForIndex]) -> _Context:
        prices = await self._pricing.search_prices([p.id for p in profiles])
        own = {category for p in profiles for category in p.category_ids}
        priced = {category for summary in prices.values() for category in summary.by_category}
        categories = {c.id: c for c in await self._catalog.categories(own | priced)}
        terms = await self._catalog.search_terms(own)
        # все кварталы города — «Весь Нови-Сад»: первый по алфавиту основным районом не показываем
        whole_city = {p.id for p in profiles if await self._geo.covers_city(p.city_id, p.area_ids)}
        districts: dict[DistrictId, DistrictSummary] = {}
        for district_id in {p.area_ids[0] for p in profiles if p.area_ids}:
            district = await self._geo.district(district_id)
            if district is not None:
                districts[district_id] = district
        avatars = [p.avatar_media_id for p in profiles if p.avatar_media_id is not None]
        refs = await self._media.refs(avatars) if avatars else {}
        ratings = await self._reviews.summaries([p.id for p in profiles])
        return _Context(
            prices=prices,
            categories=categories,
            terms=terms,
            districts=districts,
            avatars=refs,
            ratings=ratings,
            whole_city=whole_city,
        )

    def _entry(self, profile: ProfileForIndex, context: _Context) -> IndexEntry:
        prices = context.prices.get(profile.id, SearchPrices())
        rating = context.ratings.get(profile.id)
        paths = {c.id: c.path for c in context.categories.values()}
        own = [context.categories[c] for c in profile.category_ids if c in context.categories]
        media = profile.avatar_media_id
        avatar = _avatar(context.avatars.get(media) if media is not None else None)
        activity = activity_score(
            has_avatar=avatar is not None,
            about=profile.about,
            has_prices=prices.price_from is not None,
            updated_at=profile.updated_at,
            now=self._clock.now(),
        )
        whole_city = profile.id in context.whole_city
        district = (
            context.districts.get(profile.area_ids[0])
            if profile.area_ids and not whole_city
            else None
        )
        return IndexEntry(
            profile_id=profile.id,
            user_id=profile.user_id,
            kind=profile.kind,
            is_listed=profile.listed_in_catalog,
            city_id=profile.city_id,
            district_id=profile.area_ids[0] if profile.area_ids else None,
            district_ids=profile.area_ids,
            base_point=profile.base_point,
            base_point_public=profile.base_point_public,
            travel_radius_m=(
                profile.travel_radius_km * METERS_IN_KM if profile.travel_radius_km else None
            ),
            category_ids=with_ancestors(c.path for c in own),
            languages=profile.languages,
            work_modes=profile.work_modes,
            price_from=prices.price_from,
            category_prices=category_prices(prices.by_category, paths),
            available_until=profile.available_until,
            activity_score=activity,
            rating_bayes=rating.average if rating is not None else None,
            rating_lower_bound=rating.lower_bound if rating is not None else None,
            rating_count=rating.count if rating is not None else 0,
            score=base_score(
                rating_lower_bound=(
                    rating.lower_bound if rating is not None else NO_REVIEWS_LOWER_BOUND
                ),
                trust=0.0,
                activity=activity,
            ),
            name=profile.display_name,
            document=_document(profile, own, context.terms, prices),
            card=_card(
                profile,
                prices,
                category_price_units(prices.by_category, prices.unit_by_category, paths),
                avatar,
                district,
                rating,
                whole_city=whole_city,
            ),
            source_updated_at=profile.updated_at,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class _Context:
    prices: Mapping[UUID, SearchPrices]
    categories: Mapping[CategoryId, CategorySummary]
    terms: Mapping[CategoryId, tuple[SearchTerm, ...]]
    districts: Mapping[DistrictId, DistrictSummary]
    avatars: Mapping[MediaId, MediaRef]
    ratings: Mapping[UUID, RatingSummary]
    whole_city: Collection[UUID]
    """Профили, чьи районы — все кварталы города (GeoApi.covers_city)."""


def _document(
    profile: ProfileForIndex,
    categories: list[CategorySummary],
    terms: Mapping[CategoryId, tuple[SearchTerm, ...]],
    prices: SearchPrices,
) -> SearchDocument:
    names, synonyms = Labels(), Labels()
    for category in categories:
        for locale, text in category.name.values.items():
            names.add(locale.value, text)
        for term in terms.get(category.id, ()):
            synonyms.add(term.lang.value, term.term)
    about = " . ".join(part for part in (profile.headline, profile.about) if part)
    return SearchDocument(
        names_ru=" ; ".join((profile.display_name, names.joined(*_LANG_GROUPS["ru"]))),
        names_sr=serbian(" ; ".join((profile.display_name, names.joined(*_LANG_GROUPS["sr"])))),
        names_en=names.joined(*_LANG_GROUPS["en"]),
        terms_ru=synonyms.joined(*_LANG_GROUPS["ru"]),
        terms_sr=serbian(synonyms.joined(*_LANG_GROUPS["sr"])),
        terms_en=synonyms.joined(*_LANG_GROUPS["en"]),
        prices=" ; ".join(prices.titles),
        about=about,
    )


def _avatar(ref: MediaRef | None) -> dict[str, Any] | None:
    """Фото — только готовое: пока оно обрабатывается, в карточке инициалы. Ссылку на вариант
    строит выдача (4.2): у presigned-ссылок короткий срок."""
    if ref is None or ref.status != "ready":
        return None
    return {"media_id": str(ref.id), "placeholder": ref.placeholder}


def _card(
    profile: ProfileForIndex,
    prices: SearchPrices,
    units: Mapping[CategoryId, str | None],
    avatar: dict[str, Any] | None,
    district: DistrictSummary | None,
    rating: RatingSummary | None = None,
    *,
    whole_city: bool = False,
) -> dict[str, Any]:
    """Готовая карточка выдачи S05 без JOIN: время и расстояние выдача берёт из колонок. Единица
    цены «от» — только для показа («от 1 000 RSD/час»), поэтому в карточке, а не колонкой: по всему
    прайсу и по каждой категории с ценой (выдача в категории показывает её цену)."""
    return {
        "display_name": profile.display_name,
        "headline": profile.headline,
        "kind": profile.kind,
        "avatar": avatar,
        "district": (
            {
                "id": district.id,
                "name": {locale.value: text for locale, text in district.name.values.items()},
            }
            if district is not None
            else None
        ),
        "whole_city": whole_city,
        "languages": list(profile.languages),
        "category_ids": list(profile.category_ids),
        "price_from": prices.price_from,
        "price_from_unit": prices.price_from_unit,
        "category_price_units": {str(category): unit for category, unit in units.items()},
        "negotiable": prices.price_from is None and bool(prices.titles),
        # показ — простое среднее звёзд, как на S08 и S11 (UXM-17); байесовское — в колонке для
        # фильтра и сортировки
        "rating": rating.mean if rating is not None else None,
        "rating_count": 0,
        "response_time_median": None,
    }
