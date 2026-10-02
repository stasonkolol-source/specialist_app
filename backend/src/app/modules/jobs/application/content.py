"""Содержимое заявки из того, что прислал клиент (создание и правка, DEVELOPMENT_PLAN 5.1).

Проверяется по справочникам и файлам: услуга принимает заявки (активна, не запрещена, заявки
включены), город открыт, район — этого города, точка — в зоне сервиса (район по ней, если не
выбран), фото — свои и для заявок. Точная точка остаётся приватной, наружу — смещённая на
300–500 м, стабильная для заявки (§7.6). Лимит откликов — из категории.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from app.modules.catalog.api import CatalogApi, RiskLevel
from app.modules.geo.api import GeoApi
from app.modules.jobs.domain.job import Budget, JobContent, JobId, Place, Urgency
from app.modules.jobs.errors import InvalidJobError, JobCategoryError
from app.modules.media.api import MediaApi
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, MediaId, UserId

JOB_PURPOSE: Final = "job"
"""Назначение файла media: фото к заявке (S20b)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class JobDraft:
    """Что прислал клиент (POST и PATCH /jobs)."""

    title: str
    description: str
    category_id: CategoryId
    urgency: Urgency
    budget: Budget
    city_id: CityId
    content_lang: str
    district_id: DistrictId | None = None
    point: GeoPoint | None = None
    address_private: str | None = None
    preferred_from: datetime | None = None
    preferred_to: datetime | None = None
    languages: tuple[str, ...] = ()
    media_ids: tuple[MediaId, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class BuiltContent:
    content: JobContent
    max_responses: int
    risk_level: int


class ContentBuilder:
    def __init__(self, catalog: CatalogApi, geo: GeoApi, media: MediaApi) -> None:
        self._catalog, self._geo, self._media = catalog, geo, media

    async def build(self, job_id: JobId, owner_id: UserId, draft: JobDraft) -> BuiltContent:
        """Проверить по справочникам и собрать; вызывать до транзакции (чтение)."""
        category = await self._catalog.category(draft.category_id)
        if (
            category is None
            or not category.is_active
            or not category.jobs_enabled
            or category.risk_level >= RiskLevel.FORBIDDEN
        ):
            raise JobCategoryError(category_id=draft.category_id)
        place = await self._place(job_id, draft)
        for media_id in dict.fromkeys(draft.media_ids):
            await self._media.owned(owner_id, media_id, purpose=JOB_PURPOSE)
        content = JobContent(
            title=draft.title,
            description=draft.description,
            category_id=category.id,
            category_path=category.path,
            urgency=draft.urgency,
            budget=draft.budget,
            place=place,
            content_lang=draft.content_lang,
            preferred_from=draft.preferred_from,
            preferred_to=draft.preferred_to,
            languages=tuple(dict.fromkeys(draft.languages)),
            media_ids=tuple(dict.fromkeys(draft.media_ids)),
        )
        return BuiltContent(
            content=content,
            max_responses=category.max_responses,
            risk_level=int(category.risk_level),
        )

    async def _place(self, job_id: JobId, draft: JobDraft) -> Place:
        city = await self._geo.city(draft.city_id)
        if city is None or not city.is_active:
            raise InvalidJobError(field="city_id", reason="unavailable")
        district_id = draft.district_id
        if district_id is not None:
            district = await self._geo.district(district_id)
            if district is None or district.city_id != city.id:
                raise InvalidJobError(field="district_id", reason="not_in_city")
        if draft.point is None:
            return Place(
                city_id=city.id, district_id=district_id, address_private=draft.address_private
            )
        resolved = await self._geo.resolve(draft.point)
        if resolved is None or resolved.district.city_id != city.id:
            raise InvalidJobError(field="point", reason="outside_city")
        return Place(
            city_id=city.id,
            district_id=district_id if district_id is not None else resolved.district.id,
            point_exact=draft.point,
            point_public=self._geo.public_point(draft.point, seed=job_id.bytes),
            address_private=draft.address_private,
        )
