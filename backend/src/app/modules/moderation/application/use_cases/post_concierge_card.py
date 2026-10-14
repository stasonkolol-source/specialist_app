"""Карточка concierge (DEVELOPMENT_PLAN 7.1; подписчик JobPublished с задержкой CONCIERGE_AFTER).

Заявка двадцать минут после первой публикации без видимых клиенту откликов — карточка в чат
модераторов (application/concierge_card.py). Заявка читается заново: к моменту задачи её могли
закрыть, удалить, отправить на повторную проверку или на неё уже откликнулись — тогда ничего.
Прямой запрос (5.6) — тоже ничего: его видит только приглашённый, подбирать некому.

Одна карточка на заявку: задачу ставит только первая публикация (tasks.py), повторные — после
правки, продления истёкшей, отмены сделки — нет. Своих отметок модуль не хранит: подписчик
события ставится один раз (ключ — событие), а карточка — последнее, что делает задача. Тихих
часов нет: это рабочий чат команды. Чат не задан — ничего.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.catalog.api import CatalogApi
from app.modules.geo.api import GeoApi
from app.modules.jobs.api import JobReach, JobsApi
from app.modules.moderation.application.case_card import MODERATORS_LOCALE
from app.modules.moderation.application.dto import QuietJob
from app.modules.moderation.application.ports import ModeratorsChat
from app.platform.kernel.clock import Clock

PUBLISHED = "published"


@dataclass(frozen=True, slots=True, kw_only=True)
class PostConciergeCardCommand:
    job_id: UUID
    published_at: datetime
    """Первая публикация (время события): от неё — «0 откликов за N мин»."""


class PostConciergeCard:
    def __init__(
        self,
        jobs: JobsApi,
        catalog: CatalogApi,
        geo: GeoApi,
        chat: ModeratorsChat,
        clock: Clock,
    ) -> None:
        self._jobs, self._catalog, self._geo = jobs, catalog, geo
        self._chat, self._clock = chat, clock

    async def __call__(self, cmd: PostConciergeCardCommand) -> bool:
        """True — карточка отправлена."""
        if not self._chat.enabled:
            return False
        job = await self._jobs.job_reach(cmd.job_id)
        if job is None or job.status != PUBLISHED or job.direct or job.responses > 0:
            return False
        quiet = QuietJob(
            job_id=cmd.job_id,
            title=job.title,
            category=await self._category(job),
            place=await self._place(job),
            budget_type=job.budget_type,
            budget_min=job.budget_min,
            budget_max=job.budget_max,
            budget_unit=job.budget_unit,
            urgency=job.urgency,
            preferred_from=job.preferred_from,
            preferred_to=job.preferred_to,
            waited=self._clock.now() - cmd.published_at,
            notified=job.notified_count,
            pending=job.pending_responses,
        )
        await self._chat.post_quiet_job(quiet)
        return True

    async def _category(self, job: JobReach) -> str | None:
        label = (await self._catalog.labels([job.category_id])).get(job.category_id)
        return label.get(MODERATORS_LOCALE) if label is not None else None

    async def _place(self, job: JobReach) -> str | None:
        """«Лиман, Нови-Сад»; без района — город."""
        city = await self._geo.city(job.city_id)
        district = (
            (await self._geo.districts([job.district_id])).get(job.district_id)
            if job.district_id is not None
            else None
        )
        parts = [
            district.name.get(MODERATORS_LOCALE) if district is not None else None,
            city.name.get(MODERATORS_LOCALE) if city is not None else None,
        ]
        return ", ".join(part for part in parts if part) or None
