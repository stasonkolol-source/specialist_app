"""Схемы HTTP кабинета исполнителя `/me/profile*` (ARCHITECTURE §8.5)."""

from datetime import datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.media.api import MediaRef
from app.modules.specialists.application.dto import CabinetView, WorkView
from app.modules.specialists.domain.completeness import Completeness
from app.modules.specialists.domain.portfolio import LIMITS, MAX_CAPTION, WorkKind, WorkStatus
from app.modules.specialists.domain.profile import (
    MAX_ABOUT,
    MAX_AREAS,
    MAX_CATEGORIES,
    MAX_HEADLINE,
    MAX_NAME,
    Language,
    ProfileKind,
    ProfileStatus,
    WorkMode,
)
from app.platform.http.fields import INT4_MAX, CategoryIdIn, CleanText, DistrictIdIn


class ProfileCreateIn(BaseModel):
    kind: ProfileKind
    city_id: int = Field(ge=1, le=INT4_MAX)
    """Город из онбординга (GET /me)."""
    display_name: CleanText | None = Field(default=None, max_length=MAX_NAME)
    """Пусто — имя из Telegram."""


class ProfileUpdateIn(BaseModel):
    """Поля мастера S32b–c и правки S34; не переданное поле не меняется, пустая строка
    очищает «коротко о себе» и «о себе»."""

    kind: ProfileKind | None = None
    """Только у черновика (иначе 409 `profile_state_conflict`); «Подработка → Специалист» у
    проверенного профиля — POST /me/profile/become-pro."""
    display_name: CleanText | None = Field(default=None, max_length=MAX_NAME)
    headline: CleanText | None = Field(default=None, max_length=MAX_HEADLINE)
    about: CleanText | None = Field(default=None, max_length=MAX_ABOUT)
    languages: list[Language] | None = Field(default=None, max_length=len(Language))
    travel_radius_km: Literal[3, 5, 10] | None = None
    work_modes: list[WorkMode] | None = Field(default=None, max_length=len(WorkMode))


class ProfileCategoriesIn(BaseModel):
    category_ids: list[CategoryIdIn] = Field(min_length=1, max_length=MAX_CATEGORIES)
    """Первая — основная."""


class ProfileAreasIn(BaseModel):
    district_ids: list[DistrictIdIn] = Field(max_length=MAX_AREAS)


class MediaVariantOut(BaseModel):
    name: str
    """thumb, md, lg — по возрастанию ширины (у ролика — постер)."""
    url: str
    width: int
    height: int


class MediaRefOut(BaseModel):
    """Файл работы или фото профиля: пока он обрабатывается, вариантов нет."""

    id: UUID
    kind: str
    """image | video."""
    status: str
    """uploaded | processing | ready | failed | rejected."""
    placeholder: str | None
    """ThumbHash (base64) для мгновенного превью."""
    variants: list[MediaVariantOut]
    video_url: str | None
    duration_ms: int | None

    @classmethod
    def of(cls, ref: MediaRef) -> MediaRefOut:
        return cls(
            id=ref.id,
            kind=ref.kind,
            status=ref.status,
            placeholder=ref.placeholder,
            variants=[
                MediaVariantOut(name=v.name, url=v.url, width=v.width, height=v.height)
                for v in ref.variants
            ],
            video_url=ref.video_url,
            duration_ms=ref.duration_ms,
        )


class WorkOut(BaseModel):
    id: UUID
    kind: WorkKind
    caption: str | None
    position: int
    media: MediaRefOut | None
    status: WorkStatus = Field(
        description="pending — на проверке: видит только владелец; published — в карточке; "
        "rejected — скрыта модератором"
    )

    @classmethod
    def of(cls, work: WorkView) -> WorkOut:
        return cls(
            id=work.id,
            kind=work.kind,
            caption=work.caption,
            position=work.position,
            media=MediaRefOut.of(work.media) if work.media else None,
            status=work.status,
        )


class PortfolioLimitsOut(BaseModel):
    image: int
    video: int

    @classmethod
    def current(cls) -> PortfolioLimitsOut:
        return cls(image=LIMITS[WorkKind.IMAGE], video=LIMITS[WorkKind.VIDEO])


class PortfolioOut(BaseModel):
    """Портфолио в кабинете S37: работы по порядку и лимиты (60 фото, 6 роликов)."""

    items: list[WorkOut]
    limits: PortfolioLimitsOut


class WorkIn(BaseModel):
    media_id: UUID
    """Загруженный файл с назначением portfolio (POST /media/uploads)."""
    caption: CleanText | None = Field(default=None, max_length=MAX_CAPTION)


class WorkCaptionIn(BaseModel):
    caption: CleanText | None = Field(max_length=MAX_CAPTION)
    """Пустая или null — без подписи."""


class PortfolioOrderIn(BaseModel):
    item_ids: list[UUID] = Field(min_length=1, max_length=sum(LIMITS.values()))
    """Все работы в новом порядке."""


class AvatarIn(BaseModel):
    media_id: UUID | None
    """Загруженный файл с назначением avatar; null — инициалы."""


class AvailabilityIn(BaseModel):
    until: time | None
    """До которого часа сегодня принимаете заявки — по Белграду («18:00»); null — выключить."""


class HintOut(BaseModel):
    code: str
    """Что добавить: category_ids, headline, about, languages, area_ids, services,
    service_descriptions."""
    count: int | None
    """Сколько: позиций прайса без описания."""


class CompletenessOut(BaseModel):
    """Полнота профиля (S33): процент и подсказки по порядку — кабинет показывает первую."""

    percent: int
    hints: list[HintOut]

    @classmethod
    def of(cls, value: Completeness) -> CompletenessOut:
        hints = [HintOut(code=hint.code, count=hint.count) for hint in value.hints]
        return cls(percent=value.percent, hints=hints)


class ProfileOut(BaseModel):
    id: UUID
    kind: ProfileKind
    status: ProfileStatus
    display_name: str
    headline: str | None
    about: str | None
    languages: list[Language]
    city_id: int
    category_ids: list[int]
    """Первая — основная."""
    district_ids: list[int]
    travel_radius_km: int | None
    work_modes: list[WorkMode]
    listed_in_catalog: bool
    """Подработка по умолчанию в каталоге не показывается."""
    rejection_reason: str | None
    """Модерация вернула на правки: код причины (тексты — moderation_reason.*)."""
    missing: list[str]
    """Что заполнить перед отправкой на проверку: category_ids, headline, work_modes, area_ids,
    services (позиция прайса у «Специалиста»)."""
    completeness: CompletenessOut
    available_until: datetime | None
    """«Доступен сегодня до …»; null — выключено."""
    avatar: MediaRefOut | None
    """Фото профиля; null — инициалы."""
    published_at: datetime | None
    version: int

    @classmethod
    def of(cls, cabinet: CabinetView) -> ProfileOut:
        view = cabinet.profile
        return cls(
            id=view.id,
            kind=view.kind,
            status=view.status,
            display_name=view.display_name,
            headline=view.headline,
            about=view.about,
            languages=list(view.languages),
            city_id=view.city_id,
            category_ids=list(view.category_ids),
            district_ids=list(view.area_ids),
            travel_radius_km=view.travel_radius_km,
            work_modes=list(view.work_modes),
            listed_in_catalog=view.listed_in_catalog,
            rejection_reason=view.rejection_reason,
            missing=list(view.missing),
            completeness=CompletenessOut.of(cabinet.completeness),
            available_until=view.available_until,
            avatar=MediaRefOut.of(cabinet.avatar) if cabinet.avatar else None,
            published_at=view.published_at,
            version=view.version,
        )
