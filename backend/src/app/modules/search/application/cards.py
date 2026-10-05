"""Карточка специалиста из строки read-model: выдача S05 и избранное S12 (DEVELOPMENT_PLAN 4.2,
4.6). Фото профиля — вариант thumb из media; «Новый специалист» — пока отзывов меньше трёх;
«доступен сегодня до …» — только если ещё доступен.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from app.modules.media.api import MediaApi, MediaRef
from app.modules.search.application.dto import Avatar, SpecialistCard, SpecialistHit
from app.modules.search.domain.query import NEW_UNTIL_REVIEWS, rounded_distance
from app.platform.kernel.ids import MediaId

AVATAR_VARIANT: Final = "thumb"
"""320 px — карточка выдачи."""
READY = "ready"


async def specialist_cards(
    hits: Sequence[SpecialistHit], media: MediaApi, now: datetime
) -> list[SpecialistCard]:
    """Карточки строк по порядку; фото профилей — одним запросом к media."""
    wanted = {media_id for hit in hits if (media_id := _avatar_id(hit.card)) is not None}
    refs = await media.refs(wanted) if wanted else {}
    return [_card(hit, refs, now) for hit in hits]


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
        price_from_unit=hit.price_from_unit,
        negotiable=bool(card.get("negotiable")) and hit.price_from is None,
        # простое среднее из карточки (UXM-17); строка до пересборки — прежнее байесовское
        rating=None if is_new else _shown_rating(card, hit),
        rating_count=hit.rating_count,
        is_new=is_new,
        available_until=available if available is not None and available > now else None,
        badges=hit.badges,
    )


def _shown_rating(card: Mapping[str, Any], hit: SpecialistHit) -> float | None:
    shown = card.get("rating")
    return float(shown) if shown is not None else hit.rating_bayes
