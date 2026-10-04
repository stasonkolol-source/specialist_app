"""Контракт модуля specialists для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из specialists только этот файл. Модерация (выше по DAG) проверяет
профиль через адаптер цели: читает текст и публикует или возвращает на правки.
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.specialists.errors import ProfileNotFoundError as ProfileNotFoundError
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, MediaId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileForIndex:
    """Профиль для read-model поиска (search, 4.1): всё, что видит выдача, одним объектом."""

    id: UUID
    user_id: UserId
    kind: str
    status: str
    listed_in_catalog: bool
    display_name: str
    headline: str | None
    about: str | None
    languages: tuple[str, ...]
    city_id: CityId
    area_ids: tuple[DistrictId, ...]
    """Районы выезда по порядку: первый — основной."""
    base_point: GeoPoint | None
    """Точная база — только для фильтра «выезжает ко мне», наружу не отдаётся."""
    base_point_public: GeoPoint | None
    travel_radius_km: int | None
    work_modes: tuple[str, ...]
    category_ids: tuple[CategoryId, ...]
    """Категории по порядку: первая — основная."""
    available_until: datetime | None
    avatar_media_id: MediaId | None
    published_at: datetime | None
    updated_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class PublicWork:
    """Опубликованная работа портфолио (S08, S10); готов ли файл — решает media."""

    id: UUID
    kind: str
    """image | video."""
    caption: str | None
    media_id: MediaId


@dataclass(frozen=True, slots=True, kw_only=True)
class PublicProfile:
    """Опубликованный профиль для карточки специалиста S08 (4.5): что видит клиент."""

    id: UUID
    user_id: UserId
    kind: str
    display_name: str
    headline: str | None
    about: str | None
    languages: tuple[str, ...]
    city_id: CityId
    area_ids: tuple[DistrictId, ...]
    """Районы выезда по порядку: первый — основной."""
    travel_radius_km: int | None
    work_modes: tuple[str, ...]
    category_ids: tuple[CategoryId, ...]
    available_until: datetime | None
    avatar_media_id: MediaId | None
    is_founding: bool
    published_at: datetime | None
    works: tuple[PublicWork, ...]
    """Опубликованные работы портфолио по порядку S37."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PublicCard:
    """Опубликованный профиль карточкой исполнителя (S23, S26, приглашения): без описаний,
    категорий и портфолио — одним запросом на пачку."""

    id: UUID
    user_id: UserId
    kind: str
    display_name: str
    avatar_media_id: MediaId | None
    primary_area_id: DistrictId | None
    """Основной район выезда (первый по порядку)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileForReview:
    """Что проверяет модерация: текст профиля без контактов автора не очищен — это делает
    конвейер (ai/prompt.py)."""

    user_id: UserId
    text: str
    """Имя, «коротко о себе» и «о себе» — одним текстом."""
    version: int
    first_review: bool
    """Новый профиль или переход в «Специалист»: проверяет человек (P2, §14.1)."""
    risk_level: int
    """Самый строгий риск категорий профиля (catalog)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileRef:
    """Профиль пользователя для модулей выше по DAG (прайс, портфолио, переписка)."""

    id: UUID
    kind: str
    status: str
    display_name: str | None = None
    """Имя на карточке: в переписке у специалиста — оно, а не имя аккаунта."""
    is_founding: bool = False
    """Founding (§15.2): аудитория рассылки «Founding-специалистам» (2.7b, Q24)."""
    city_id: CityId | None = None
    """Город профиля: аудитория рассылки по городу (2.7b)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PortfolioWorkRef:
    """Работа портфолио с этим файлом — для кейса о дубликате фото (7.6, ADR-0016 L6)."""

    id: UUID
    profile_id: UUID
    status: str
    """pending | published | rejected."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceSummary:
    """Прайс профиля для полноты в кабинете (S33): видимые позиции и сколько из них без
    описания."""

    items: int = 0
    without_description: int = 0


class PriceList(Protocol):
    """Прайс профиля — его ведёт pricing (выше по DAG): specialists спрашивает через этот порт,
    pricing реализует, связывает dishka (как LegalHold у media)."""

    async def has_items(self, profile_id: UUID) -> bool:
        """Есть ли видимая позиция прайса: без неё «Специалиста» на проверку не отправить."""
        ...

    async def summary(self, profile_id: UUID) -> PriceSummary:
        """Сколько видимых позиций и сколько из них без описания."""
        ...


class SpecialistsApi(Protocol):
    async def profile_of(self, user_id: UserId) -> ProfileRef | None:
        """Профиль пользователя; None — его нет (или удалён)."""
        ...

    async def profiles_of(self, user_ids: Collection[UserId]) -> dict[UserId, ProfileRef]:
        """Профили пользователей пачкой (список диалогов S29: ссылка на карточку); без профиля
        или с удалённым — нет в ответе."""
        ...

    async def profile_for_review(self, profile_id: UUID) -> ProfileForReview | None:
        """Профиль на проверке или опубликованный (пост-модерация правок); None — нет такого,
        удалён или проверять нечего (черновик, приостановлен)."""
        ...

    async def approve_profile(self, profile_id: UUID, *, version: int | None) -> None:
        """Проверка пройдена — в транзакции вызывающего: ждавший проверки публикуется;
        другая версия или статус — ничего."""
        ...

    async def reject_profile(self, profile_id: UUID, *, reason_code: str) -> None:
        """Нарушение — в транзакции вызывающего: ждавший проверки возвращается на правки,
        опубликованный приостанавливается."""
        ...

    async def profiles_for_index(self, profile_ids: Collection[UUID]) -> list[ProfileForIndex]:
        """Профили для поиска в любом статусе (решает вызывающий); удалённых нет."""
        ...

    async def public_profile(self, profile_id: UUID) -> PublicProfile | None:
        """Опубликованный профиль с работами портфолио (S08). Черновик, скрытый, удалённый или
        несуществующий — None. Санкции автора проверяет вызывающий (identity)."""
        ...

    async def public_cards(self, profile_ids: Collection[UUID]) -> dict[UUID, PublicCard]:
        """Опубликованные профили карточками — пачкой; черновика, скрытого, удалённого и
        несуществующего нет в ответе. Санкции автора проверяет вызывающий (identity)."""
        ...

    async def published_profile_ids(self, *, after: UUID | None, limit: int) -> list[UUID]:
        """Опубликованные профили по id после `after` — сверка индекса поиска."""
        ...

    async def works_by_media(
        self, media_ids: Collection[MediaId]
    ) -> dict[MediaId, PortfolioWorkRef]:
        """Неудалённые работы портфолио с этими файлами — пачкой; файла не в портфолио (ещё не
        прикреплён или работу убрали) в ответе нет."""
        ...
