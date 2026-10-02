"""Схемы HTTP выдачи специалистов (DEVELOPMENT_PLAN 4.2): карточки S05 и страница выдачи."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.catalog.api import CategorySuggestion
from app.modules.search.application.dto import SpecialistCard, SpecialistResults
from app.platform.http.pagination import PageOut
from app.platform.kernel.localized import Locale, LocalizedText


class CardAvatarOut(BaseModel):
    url: str
    width: int
    height: int
    placeholder: str | None = Field(description="ThumbHash (base64) для мгновенного превью")


class CardDistrictOut(BaseModel):
    id: int
    name: str


class SpecialistCardOut(BaseModel):
    profile_id: UUID
    display_name: str
    headline: str | None
    kind: str = Field(description="pro | casual")
    avatar: CardAvatarOut | None
    district: CardDistrictOut | None
    distance_m: int | None = Field(description="От точки клиента, шагом 500 м; без точки — нет")
    languages: list[str]
    category_ids: list[int]
    price_from: int | None = Field(description="Цена «от», пара (1 RSD = 100 пара)")
    negotiable: bool = Field(description="Цены нет, но прайс есть: «договорная»")
    rating: float | None = Field(description="Когда отзывов достаточно; иначе is_new")
    rating_count: int
    is_new: bool = Field(description="«Новый специалист»: отзывов меньше трёх")
    available_until: datetime | None = Field(description="«Доступен сегодня до …»")
    badges: list[str]

    @classmethod
    def of(cls, card: SpecialistCard, locale: Locale) -> SpecialistCardOut:
        avatar = card.avatar
        district = None
        if card.district_id is not None and card.district_name:
            name = LocalizedText.from_mapping(card.district_name).get(locale)
            district = CardDistrictOut(id=card.district_id, name=name)
        return cls(
            profile_id=card.profile_id,
            display_name=card.display_name,
            headline=card.headline,
            kind=card.kind,
            avatar=(
                CardAvatarOut(
                    url=avatar.url,
                    width=avatar.width,
                    height=avatar.height,
                    placeholder=avatar.placeholder,
                )
                if avatar is not None
                else None
            ),
            district=district,
            distance_m=card.distance_m,
            languages=list(card.languages),
            category_ids=list(card.category_ids),
            price_from=card.price_from,
            negotiable=card.negotiable,
            rating=card.rating,
            rating_count=card.rating_count,
            is_new=card.is_new,
            available_until=card.available_until,
            badges=list(card.badges),
        )


class SpecialistPageOut(PageOut[SpecialistCardOut]):
    category_ids: list[int] = Field(
        default_factory=list, description="Категории, в которых узнан запрос: чип над выдачей"
    )
    did_you_mean: str | None = Field(
        default=None, description="«Возможно, вы имели в виду …»: выдача — по этому слову"
    )
    hints: list[str] = Field(
        default_factory=list, description="Пустая выдача: relax_filters, post_job"
    )

    @classmethod
    def from_results(cls, results: SpecialistResults, locale: Locale) -> SpecialistPageOut:
        page = results.page
        return cls(
            items=[SpecialistCardOut.of(card, locale) for card in page.items],
            next_cursor=page.next_cursor,
            category_ids=list(results.category_ids),
            did_you_mean=results.did_you_mean,
            hints=list(results.hints),
        )


class SuggestionOut(BaseModel):
    category_id: int
    name: str = Field(description="Название категории на языке Accept-Language")
    icon: str | None
    term: str = Field(description="Слово словаря, с которым совпал ввод, — тем же алфавитом")
    fuzzy: bool = Field(description="Найдено по похожести (опечатка), а не по началу слова")


class SuggestOut(BaseModel):
    items: list[SuggestionOut]

    @classmethod
    def of(cls, found: list[CategorySuggestion], locale: Locale) -> SuggestOut:
        return cls(
            items=[
                SuggestionOut(
                    category_id=item.category_id,
                    name=item.name.get(locale),
                    icon=item.icon,
                    term=item.term,
                    fuzzy=item.fuzzy,
                )
                for item in found
            ]
        )


class SpecialistCountOut(BaseModel):
    count: int
    capped: bool = Field(description="Подходит больше, чем считали: «Показать 1000+»")


class CategoryCountOut(BaseModel):
    category_id: int
    count: int = Field(description="Видимые специалисты — с подкатегориями")


class CategoryCountsOut(BaseModel):
    items: list[CategoryCountOut]
