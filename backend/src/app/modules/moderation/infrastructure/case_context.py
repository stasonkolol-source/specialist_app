"""Контекст карточки кейса в чате модераторов (DEVELOPMENT_PLAN 2.5b; порт CaseContextQuery).

Кто, что и почему — через фасады модулей-владельцев (identity, specialists, jobs, messaging,
reviews, media, deals, catalog, geo), без их внутренностей; жалобы и обжалованное решение — свои
таблицы moderation. Отдаём только то, что карточке можно показать (граница приватности —
application/case_card.py): публичное имя, роль, район, сам проверяемый текст. Телефон, Telegram,
адрес и точку заявки, переписку и доказательства спора отсюда не берём вовсе.

Пропавшее — не ошибка: удалённый пользователь — «удалённый пользователь», снятый объект —
«уже нет, смотреть в админке», фото не прочитать из хранилища — карточка уходит текстом.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Final
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.api import CatalogApi
from app.modules.deals.api import DealsApi
from app.modules.geo.api import GeoApi
from app.modules.identity.api import IdentityApi
from app.modules.jobs.api import JobsApi
from app.modules.media.api import MediaApi
from app.modules.messaging.api import MessagingApi
from app.modules.moderation.application.case_card import MODERATORS_LOCALE
from app.modules.moderation.application.dto import (
    AppealContext,
    BudgetContext,
    CaseContext,
    CaseObject,
    CasePhoto,
    ContentField,
    DisputeContext,
    PersonContext,
    ReportContext,
)
from app.modules.moderation.application.ports import CaseContextQuery, CasePhotos
from app.modules.moderation.domain.cases import Case, CaseTrigger, EntityType
from app.modules.moderation.domain.reports import ReportStatus
from app.modules.moderation.infrastructure.models import CaseRow, ReportRow
from app.modules.reviews.api import ReviewsApi
from app.modules.specialists.api import SpecialistsApi
from app.platform.db.query import SqlQuery
from app.platform.kernel.errors import ExternalServiceError
from app.platform.kernel.ids import CategoryId, DistrictId, MediaId, UserId
from app.platform.text.names import short_name

log = structlog.get_logger(__name__)

CLIENT: Final = "client"
PHOTO_KINDS: Final[Mapping[str, str]] = {
    "avatar": "avatar",
    "portfolio": "portfolio_photo",
    "job": "job_photo",
}
"""Назначение фото (`MediaReady.purpose` в поводе кейса) → объект карточки."""
DUPLICATE: Final = "portfolio_duplicate"


class FacadeCaseContext(SqlQuery, CaseContextQuery):
    def __init__(
        self,
        session: AsyncSession,
        identity: IdentityApi,
        specialists: SpecialistsApi,
        jobs: JobsApi,
        messaging: MessagingApi,
        reviews: ReviewsApi,
        photos: CasePhotos,
        deals: DealsApi,
        catalog: CatalogApi,
        geo: GeoApi,
    ) -> None:
        super().__init__(session)
        self._identity, self._specialists, self._jobs = identity, specialists, jobs
        self._messaging, self._reviews, self._photos = messaging, reviews, photos
        self._deals, self._catalog, self._geo = deals, catalog, geo

    async def context(self, case: Case) -> CaseContext:
        found = await self._object(case)
        subject = await self._person(case.subject_id, district=found.district)
        photo = None
        if found.photo_id is not None and not found.hidden:
            photo = await self._photos.photo(found.photo_id)
        return CaseContext(
            subject=subject,
            object=found.object,
            reports=await self._reports(case),
            dispute=await self._dispute(case) if case.entity_type is EntityType.DISPUTE else None,
            appeal=await self._appeal(case) if case.appeal_of is not None else None,
            photo=photo,
            photo_hidden=found.hidden,
        )

    async def _object(self, case: Case) -> _Found:
        match case.entity_type:
            case EntityType.PROFILE:
                return await self._profile(case)
            case EntityType.PORTFOLIO:
                work = await self._specialists.work_for_review(case.entity_id)
                if work is None:
                    return _Found(CaseObject(kind="portfolio", missing=True))
                fields = _fields(caption=work.caption)
                return _Found(CaseObject(kind="portfolio", fields=fields), photo_id=work.media_id)
            case EntityType.JOB:
                return await self._job(case.entity_id)
            case EntityType.RESPONSE:
                return await self._response(case.entity_id)
            case EntityType.MESSAGE:
                message = await self._messaging.message_for_card(case.entity_id)
                if message is None:
                    return _Found(CaseObject(kind="message", missing=True))
                return _Found(CaseObject(kind="message", fields=_fields(message=message.text)))
            case EntityType.REVIEW:
                return await self._review(case.entity_id)
            case EntityType.REVIEW_REPLY:
                return await self._reply(case.entity_id)
            case EntityType.MEDIA:
                return _media(case)
            case EntityType.DISPUTE:
                return _Found(CaseObject(kind="dispute"))
            case EntityType.USER:
                return _Found(CaseObject(kind="user"))

    async def _profile(self, case: Case) -> _Found:
        found = await self._specialists.profiles_for_index([case.entity_id])
        if not found:
            return _Found(CaseObject(kind="profile", missing=True))
        profile = found[0]
        fields = _fields(headline=profile.headline, about=profile.about)
        # похожее фото у другого аккаунта (7.6): само загруженное фото портфолио — в чат
        photo = next(
            (
                MediaId(UUID(str(entry["media_id"])))
                for entry in case.evidence
                if DUPLICATE in _signals(entry) and entry.get("media_id")
            ),
            None,
        )
        return _Found(CaseObject(kind="profile", fields=fields), photo_id=photo)

    async def _job(self, job_id: UUID) -> _Found:
        job = await self._jobs.job_for_review(job_id)
        if job is None:
            return _Found(CaseObject(kind="job", missing=True))
        budget = None
        if job.budget_type:
            budget = BudgetContext(
                kind=job.budget_type, low=job.budget_min, high=job.budget_max, unit=job.budget_unit
            )
        title, description = (job.title, job.description) if job.title else (job.text, "")
        fields = _fields(title=title, description=description)
        return _Found(
            CaseObject(kind="job", fields=fields, budget=budget),
            district=await self._district(job.district_id),
        )

    async def _response(self, response_id: UUID) -> _Found:
        response = await self._jobs.chat_response(response_id)
        if response is None:
            return _Found(CaseObject(kind="response", missing=True))
        titles = await self._jobs.job_titles([response.job_id])
        fields = _fields(
            job=titles.get(response.job_id),
            message=response.message,
            availability=response.availability_note,
        )
        return _Found(CaseObject(kind="response", fields=fields))

    async def _review(self, review_id: UUID) -> _Found:
        pending = await self._reviews.review_for_check(review_id)
        if pending is not None:
            return _Found(
                CaseObject(kind="review", fields=_fields(text=pending.text), rating=pending.rating)
            )
        published = await self._reviews.published_review(review_id)
        if published is None:
            return _Found(CaseObject(kind="review", missing=True))
        text = "\n".join(part for part in (published.work_title, published.body) if part)
        return _Found(CaseObject(kind="review", fields=_fields(text=text), rating=published.rating))

    async def _reply(self, review_id: UUID) -> _Found:
        pending = await self._reviews.reply_for_check(review_id)
        text = pending.text if pending is not None else None
        if text is None:
            published = await self._reviews.published_review(review_id)
            text = published.reply.body if published and published.reply else None
        if text is None:
            return _Found(CaseObject(kind="review_reply", missing=True))
        return _Found(CaseObject(kind="review_reply", fields=_fields(text=text)))

    async def _person(self, user_id: UserId, *, district: str | None = None) -> PersonContext:
        """Человек кейса: имя, как его видит приложение (у специалиста — имя профиля)."""
        opened, total = await self._complaints(user_id)
        user = await self._identity.get_user(user_id)
        if user is None or user.is_deleted:
            return PersonContext(name=None, complaints_open=opened, complaints_total=total)
        profile = (await self._specialists.profiles_of([user_id])).get(user_id)
        name, role, category = user.display_name, CLIENT, None
        if profile is not None:
            name, role = profile.display_name or name, profile.kind
            indexed = await self._specialists.profiles_for_index([profile.id])
            if indexed:
                category = await self._category(indexed[0].category_ids)
                district = await self._district(next(iter(indexed[0].area_ids), None))
        return PersonContext(
            name=short_name(name),
            role=role,
            category=category,
            district=district,
            joined_at=user.created_at,
            trust_level=user.trust_level,
            deals_done=await self._deals.completed_deals(user_id),
            complaints_open=opened,
            complaints_total=total,
        )

    async def _reports(self, case: Case) -> tuple[ReportContext, ...]:
        """Жалобы этого кейса: причина, роль жалующегося и его текст (обрежет карточка)."""
        report_ids = [
            UUID(str(entry["report_id"]))
            for entry in case.evidence
            if entry.get("trigger") == CaseTrigger.REPORT.value and entry.get("report_id")
        ]
        if not report_ids:
            return ()
        r = ReportRow.__table__.c
        rows = await self._fetch(
            select(r.id, r.reporter_id, r.reason, r.comment)
            .where(r.id.in_(report_ids))
            .order_by(r.created_at)
        )
        roles = await self._roles([UserId(row["reporter_id"]) for row in rows])
        return tuple(
            ReportContext(
                reason=str(row["reason"]),
                reporter_role=roles.get(UserId(row["reporter_id"])),
                comment=row["comment"],
            )
            for row in rows
        )

    async def _dispute(self, case: Case) -> DisputeContext | None:
        dispute = await self._deals.dispute(case.entity_id)
        if dispute is None:
            return None
        title = next((str(e["title"]) for e in case.evidence if e.get("title")), None)
        if title is None:
            deal = await self._deals.deal_brief(dispute.deal_id)
            title = deal.title if deal is not None else None
        names = await self._names([dispute.opened_by, dispute.respondent_id])
        return DisputeContext(
            kind=dispute.kind,
            title=title,
            opened_by=names.get(dispute.opened_by),
            respondent=names.get(dispute.respondent_id),
            answered=dispute.responded_at is not None,
            photos=len(case.media_ids),
        )

    async def _appeal(self, case: Case) -> AppealContext | None:
        c = CaseRow.__table__.c
        row = await self._fetch_one(
            select(c.reason_code, c.decided_at).where(c.id == case.appeal_of)
        )
        if row is None:
            return None
        return AppealContext(reason_code=row["reason_code"], decided_at=row["decided_at"])

    async def _complaints(self, user_id: UserId) -> tuple[int, int]:
        """Жалобы на человека: открытые и все — по кейсам о нём."""
        r, c = ReportRow.__table__.c, CaseRow.__table__.c
        row = await self._fetch_one(
            select(
                func.count().filter(r.status == ReportStatus.OPEN.value).label("open"),
                func.count().label("total"),
            )
            .select_from(ReportRow.__table__.join(CaseRow.__table__, c.id == r.case_id))
            .where(c.subject_id == user_id)
        )
        return (int(row["open"]), int(row["total"])) if row is not None else (0, 0)

    async def _roles(self, user_ids: Collection[UserId]) -> dict[UserId, str]:
        """Роль людей (жалующихся): вид профиля или «клиент»; удалённых нет в ответе."""
        users = await self._identity.users(user_ids)
        alive = [user_id for user_id, user in users.items() if not user.is_deleted]
        profiles = await self._specialists.profiles_of(alive)
        return {
            user_id: profiles[user_id].kind if user_id in profiles else CLIENT for user_id in alive
        }

    async def _names(self, user_ids: Collection[UserId]) -> dict[UserId, str]:
        """Публичные имена («Ana P.»): у специалиста — имя профиля; удалённых нет в ответе."""
        users = await self._identity.users(user_ids)
        alive = [user_id for user_id, user in users.items() if not user.is_deleted]
        profiles = await self._specialists.profiles_of(alive)
        names = {}
        for user_id in alive:
            profile = profiles.get(user_id)
            shown = profile.display_name if profile and profile.display_name else None
            names[user_id] = short_name(shown or users[user_id].display_name)
        return names

    async def _category(self, category_ids: Collection[CategoryId]) -> str | None:
        main = next(iter(category_ids), None)
        if main is None:
            return None
        labels = await self._catalog.labels([main])
        return labels[main].get(MODERATORS_LOCALE) if main in labels else None

    async def _district(self, district_id: DistrictId | None) -> str | None:
        if district_id is None:
            return None
        district = await self._geo.district(district_id)
        return district.name.get(MODERATORS_LOCALE) if district is not None else None


class MediaCasePhotos(CasePhotos):
    """Фото карточки из хранилища media (MediaApi.image_for_card)."""

    def __init__(self, media: MediaApi) -> None:
        self._media = media

    async def photo(self, media_id: MediaId) -> CasePhoto | None:
        """Хранилище недоступно — карточка уйдёт текстом, а не повтором задачи."""
        try:
            image = await self._media.image_for_card(media_id)
        except ExternalServiceError:
            log.warning("moderation_card_photo_unavailable", media_id=str(media_id))
            return None
        return CasePhoto(body=image.body, content_type=image.content_type) if image else None


class NoCasePhotos(CasePhotos):
    """S3 не настроен (бот или тесты без хранилища): карточки кейсов о фото — текстом."""

    async def photo(self, media_id: MediaId) -> CasePhoto | None:  # noqa: ARG002
        return None


@dataclass(frozen=True, slots=True)
class _Found:
    """Объект кейса и то, что карточке нужно рядом с ним: фото и район заявки."""

    object: CaseObject
    photo_id: MediaId | None = None
    hidden: bool = False
    """Фото скрыто автоматически (P0): в чат не шлём."""
    district: str | None = None


def _media(case: Case) -> _Found:
    """Кейс проверки фото (6.7): что за фото — по назначению в поводе; скрытое при P0 в чат не
    уходит."""
    first = case.evidence[0] if case.evidence else {}
    kind = PHOTO_KINDS.get(str(first.get("purpose")), "photo")
    hidden = any(bool(entry.get("hidden")) for entry in case.evidence)
    return _Found(CaseObject(kind=kind), photo_id=MediaId(case.entity_id), hidden=hidden)


def _fields(**parts: str | None) -> tuple[ContentField, ...]:
    return tuple(ContentField(name=name, text=text) for name, text in parts.items() if text)


def _signals(entry: Mapping[str, object]) -> list[str]:
    signals = entry.get("signals")
    return [str(signal) for signal in signals] if isinstance(signals, list) else []
