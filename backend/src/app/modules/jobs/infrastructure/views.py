"""Просмотры заявки (S23 «просмотры», DEVELOPMENT_PLAN 5.6): не владелец открыл заявку — счётчик
`jobs.views_count` растёт, но от одного человека не чаще раза в сутки (окно платформенного
лимитера на Valkey). Счётчик пишется отдельным UPDATE мимо агрегата: просмотр не меняет версию
заявки (If-Match владельца) и не рождает событий."""

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.jobs.domain.job import JobId
from app.modules.jobs.infrastructure.models import JobRow
from app.platform.db.port import UnitOfWork
from app.platform.kernel.errors import RateLimitedError
from app.platform.kernel.ids import UserId
from app.platform.ratelimit import Rate, RateLimiter

VIEW = Rate("jobs.view", "1/day")
"""Один просмотр заявки от одного человека в сутки."""
_J = JobRow.__table__.c


class LimitedJobViews:
    def __init__(self, session: AsyncSession, uow: UnitOfWork, limiter: RateLimiter) -> None:
        self._session, self._uow, self._limiter = session, uow, limiter

    async def count(self, job_id: JobId, viewer_id: UserId) -> None:
        self._uow.require_active()
        try:
            await self._limiter.hit(VIEW, f"{job_id}:{viewer_id}")
        except RateLimitedError:
            return
        await self._session.execute(
            update(JobRow)
            .where(_J.id == job_id)
            .values(views_count=_J.views_count + 1)
            .execution_options(synchronize_session=False)
        )
