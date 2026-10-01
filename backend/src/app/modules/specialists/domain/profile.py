"""Профиль исполнителя (ARCHITECTURE §7.3, §7.9; DEVELOPMENT_PLAN 2.8a).

`pro` — специалист в каталоге; `casual` — подработка, по умолчанию не в каталоге. Один
профиль на пользователя. Жизненный цикл:
    draft → pending_review → published ↔ hidden
    pending_review → draft          (модерация вернула на правки: `rejection_reason`)
    published | hidden → suspended  (модерация скрыла опубликованный)
Новый профиль и переход «Подработка → Специалист» всегда проверяет человек (P2, §14.1).
Правки опубликованного применяются сразу и уходят на пост-модерацию.
"""

import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Final, NewType
from uuid import UUID

from app.modules.specialists.errors import (
    InvalidProfileError,
    ProfileIncompleteError,
    ProfileStateError,
)
from app.platform.contracts.events.specialists import (
    ProfileHidden,
    ProfilePublished,
    ProfileSubmitted,
    ProfileUpdated,
)
from app.platform.kernel.aggregate import VersionedAggregate
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, UserId, new_id

ProfileId = NewType("ProfileId", UUID)

MAX_NAME: Final = 64
MAX_HEADLINE: Final = 80
MAX_ABOUT: Final = 4000
MAX_CATEGORIES: Final = 5
"""Категорий в профиле **[Допущение]**: специалист — не «мастер на все руки»."""
MAX_AREAS: Final = 30
TRAVEL_RADII_KM: Final = frozenset({3, 5, 10})
"""Радиус выезда S32c: до 3, 5 или 10 км."""


class ProfileKind(StrEnum):
    PRO = "pro"
    """Специалист: в каталоге и поиске."""
    CASUAL = "casual"
    """Подработка: задачи рядом; по умолчанию не в каталоге."""


class ProfileStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    HIDDEN = "hidden"
    SUSPENDED = "suspended"


class WorkMode(StrEnum):
    AT_CLIENT = "at_client"
    """Выезжаю к клиенту."""
    AT_OWN_PLACE = "at_own_place"
    """Принимаю у себя."""
    REMOTE = "remote"


class Language(StrEnum):
    RU = "ru"
    SR = "sr"
    EN = "en"
    UK = "uk"


VISIBLE: Final = frozenset({ProfileStatus.PUBLISHED})
"""Видно в каталоге (и в поиске, если `listed_in_catalog`)."""


@dataclass(eq=False, kw_only=True)
class Profile(VersionedAggregate):
    id: ProfileId
    user_id: UserId
    kind: ProfileKind
    status: ProfileStatus
    display_name: str
    city_id: CityId
    created_at: datetime
    headline: str | None = None
    about: str | None = None
    languages: tuple[Language, ...] = ()
    category_ids: tuple[CategoryId, ...] = ()
    """Первая — основная."""
    area_ids: tuple[DistrictId, ...] = ()
    """Районы выезда; база и публичная точка — центр первого."""
    base_point: GeoPoint | None = None
    base_point_public: GeoPoint | None = None
    travel_radius_km: int | None = None
    work_modes: tuple[WorkMode, ...] = ()
    listed_in_catalog: bool = True
    is_founding: bool = False
    available_until: datetime | None = None
    vacation_until: date | None = None
    rejection_reason: str | None = None
    """Почему модерация вернула на правки: код причины для S33 («Нужны правки»)."""
    submitted_at: datetime | None = None
    published_at: datetime | None = None
    reviewed_kind: bool = False
    """Профиль ждёт проверки после перехода «Подработка → Специалист»."""

    @classmethod
    def create(
        cls,
        *,
        user_id: UserId,
        kind: ProfileKind,
        display_name: str,
        city_id: CityId,
        now: datetime,
    ) -> Profile:
        return cls(
            id=ProfileId(new_id()),
            user_id=user_id,
            kind=kind,
            status=ProfileStatus.DRAFT,
            display_name=_name(display_name),
            city_id=city_id,
            created_at=now,
            listed_in_catalog=kind is ProfileKind.PRO,
            version=1,
        )

    @property
    def first_review(self) -> bool:
        """Проверка до публикации: новый профиль или переход в «Специалист» (всегда человек)."""
        return self.status is ProfileStatus.PENDING_REVIEW

    def edit(self, *, now: datetime, **changes: object) -> tuple[str, ...]:
        """Изменить поля (None — не менять). Возвращает изменённые; у опубликованного —
        событие ProfileUpdated: текст уйдёт на пост-модерацию."""
        self._ensure_editable()
        values = _validated(changes)
        changed = tuple(name for name, value in values.items() if getattr(self, name) != value)
        for name in changed:
            setattr(self, name, values[name])
        if changed and self.status is not ProfileStatus.DRAFT:
            self._record(
                ProfileUpdated(
                    profile_id=self.id, user_id=self.user_id, fields=changed, occurred_at=now
                )
            )
        return changed

    def set_categories(self, category_ids: Iterable[CategoryId], *, now: datetime) -> bool:
        ids = tuple(dict.fromkeys(category_ids))
        if not 1 <= len(ids) <= MAX_CATEGORIES:
            raise InvalidProfileError(field="category_ids")
        return bool(self._replace("category_ids", ids, now=now))

    def set_areas(
        self,
        area_ids: Iterable[DistrictId],
        *,
        base: GeoPoint | None,
        public: GeoPoint | None,
        now: datetime,
    ) -> bool:
        ids = tuple(dict.fromkeys(area_ids))
        if len(ids) > MAX_AREAS:
            raise InvalidProfileError(field="area_ids")
        self.base_point, self.base_point_public = base, public
        return bool(self._replace("area_ids", ids, now=now))

    def submit(self, *, now: datetime) -> None:
        """На проверку: черновик (новый или после отказа)."""
        if self.status is not ProfileStatus.DRAFT:
            raise ProfileStateError(profile_status=self.status.value)
        missing = self.missing()
        if missing:
            raise ProfileIncompleteError(missing=missing)
        self.status = ProfileStatus.PENDING_REVIEW
        self.submitted_at = now
        self.rejection_reason = None
        self._record(
            ProfileSubmitted(
                profile_id=self.id, user_id=self.user_id, kind=self.kind.value, occurred_at=now
            )
        )

    def missing(self) -> tuple[str, ...]:
        return missing_fields(
            category_ids=self.category_ids,
            headline=self.headline,
            work_modes=self.work_modes,
            area_ids=self.area_ids,
        )

    def approve(self, *, now: datetime, version: int | None = None) -> bool:
        """Модерация одобрила: опубликовать. False — нечего (не ждёт проверки, другая версия)."""
        if self.status is not ProfileStatus.PENDING_REVIEW:
            return False
        if version is not None and version != self.version:
            return False
        self.status = ProfileStatus.PUBLISHED
        self.published_at = now
        self.reviewed_kind = False
        self._record(
            ProfilePublished(
                profile_id=self.id, user_id=self.user_id, approved=True, occurred_at=now
            )
        )
        return True

    def reject(self, *, reason_code: str, now: datetime) -> None:
        """Модерация отказала: ждавший проверки — на правки, опубликованный — приостановлен."""
        if self.status is ProfileStatus.PENDING_REVIEW:
            self.status = ProfileStatus.DRAFT
            self.rejection_reason = reason_code
        elif self.status in (ProfileStatus.PUBLISHED, ProfileStatus.HIDDEN):
            self.status = ProfileStatus.SUSPENDED
            self.rejection_reason = reason_code
            self._record(
                ProfileHidden(
                    profile_id=self.id, user_id=self.user_id, by_moderation=True, occurred_at=now
                )
            )

    def hide(self, *, now: datetime) -> None:
        """Владелец скрыл профиль из каталога («Пауза»)."""
        if self.status is ProfileStatus.HIDDEN:
            return
        if self.status is not ProfileStatus.PUBLISHED:
            raise ProfileStateError(profile_status=self.status.value)
        self.status = ProfileStatus.HIDDEN
        self._record(ProfileHidden(profile_id=self.id, user_id=self.user_id, occurred_at=now))

    def show(self, *, now: datetime) -> None:
        if self.status is ProfileStatus.PUBLISHED:
            return
        if self.status is not ProfileStatus.HIDDEN:
            raise ProfileStateError(profile_status=self.status.value)
        self.status = ProfileStatus.PUBLISHED
        self._record(ProfilePublished(profile_id=self.id, user_id=self.user_id, occurred_at=now))

    def become_pro(self, *, now: datetime) -> None:
        """«Подработка → Специалист»: в каталог, но сначала — снова проверка человеком."""
        if self.kind is ProfileKind.PRO:
            return
        if self.status is ProfileStatus.SUSPENDED:
            raise ProfileStateError(profile_status=self.status.value)
        self.kind = ProfileKind.PRO
        self.listed_in_catalog = True
        if self.status in (ProfileStatus.PUBLISHED, ProfileStatus.HIDDEN):
            was_visible = self.status is ProfileStatus.PUBLISHED
            self.status = ProfileStatus.PENDING_REVIEW
            self.submitted_at = now
            self.reviewed_kind = True
            if was_visible:
                self._record(
                    ProfileHidden(profile_id=self.id, user_id=self.user_id, occurred_at=now)
                )
            self._record(
                ProfileSubmitted(
                    profile_id=self.id, user_id=self.user_id, kind=self.kind.value, occurred_at=now
                )
            )

    def mark_founding(self) -> bool:
        if self.is_founding:
            return False
        self.is_founding = True
        return True

    def _replace(self, name: str, value: tuple[object, ...], *, now: datetime) -> tuple[str, ...]:
        self._ensure_editable()
        if getattr(self, name) == value:
            return ()
        setattr(self, name, value)
        if self.status is not ProfileStatus.DRAFT:
            self._record(
                ProfileUpdated(
                    profile_id=self.id, user_id=self.user_id, fields=(name,), occurred_at=now
                )
            )
        return (name,)

    def _ensure_editable(self) -> None:
        if self.status is ProfileStatus.SUSPENDED:
            raise ProfileStateError(profile_status=self.status.value)


def missing_fields(
    *,
    category_ids: tuple[CategoryId, ...],
    headline: str | None,
    work_modes: tuple[WorkMode, ...],
    area_ids: tuple[DistrictId, ...],
) -> tuple[str, ...]:
    """Что заполнить перед проверкой (S32b–c): категория, «коротко о себе», формат работы; для
    выезда — районы."""
    missing = []
    if not category_ids:
        missing.append("category_ids")
    if not headline:
        missing.append("headline")
    if not work_modes:
        missing.append("work_modes")
    elif WorkMode.AT_CLIENT in work_modes and not area_ids:
        missing.append("area_ids")
    return tuple(missing)


EDITABLE: Final = frozenset(
    {"display_name", "headline", "about", "languages", "travel_radius_km", "work_modes"}
)
TEXT_FIELDS: Final = frozenset({"display_name", "headline", "about"})
"""Поля с текстом: их правка опубликованного профиля уходит на пост-модерацию."""


def _validated(changes: Mapping[str, object]) -> dict[str, object]:
    unknown = set(changes) - EDITABLE
    if unknown:
        raise InvalidProfileError(field=sorted(unknown)[0])
    values: dict[str, object] = {}
    for name, value in changes.items():
        if value is None:
            continue
        match name:
            case "display_name":
                values[name] = _name(str(value))
            case "headline":
                values[name] = _text(str(value), MAX_HEADLINE, name)
            case "about":
                values[name] = _text(str(value), MAX_ABOUT, name)
            case "languages":
                values[name] = _choices(value, Language, name)
            case "work_modes":
                values[name] = _choices(value, WorkMode, name)
            case "travel_radius_km":
                if value not in TRAVEL_RADII_KM:
                    raise InvalidProfileError(field=name)
                values[name] = value
    return values


def _name(value: str) -> str:
    name = " ".join(_clean(value).split())
    if not name or len(name) > MAX_NAME:
        raise InvalidProfileError(field="display_name")
    return name


def _text(value: str, limit: int, field: str) -> str | None:
    text = _clean(value).strip()
    if len(text) > limit:
        raise InvalidProfileError(field=field)
    return text or None


def _choices[E: StrEnum](value: object, enum: type[E], field: str) -> tuple[E, ...]:
    if not isinstance(value, Iterable) or isinstance(value, str):
        raise InvalidProfileError(field=field)
    try:
        return tuple(dict.fromkeys(enum(item) for item in value))
    except ValueError:
        raise InvalidProfileError(field=field) from None


def _clean(value: str) -> str:
    """Без управляющих символов и bidi-override: имя и текст показываются другим людям."""
    return "".join(
        char
        for char in unicodedata.normalize("NFC", value)
        if char in "\n\t" or unicodedata.category(char) not in {"Cc", "Cf"}
    )
