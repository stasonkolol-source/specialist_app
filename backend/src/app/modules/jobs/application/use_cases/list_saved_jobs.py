"""Сохранённые заявки S12 (DEVELOPMENT_PLAN 5.3): карточки, как в ленте, новые сохранения
первыми. Показываются открытые: закрытая или истёкшая из списка пропадает, а запись остаётся до
удаления аккаунта; так же — заявка того, с кем у зрителя блокировка (4.7). Расстояния нет: точки
зрителя у списка нет."""

from dataclasses import dataclass

from app.modules.identity.api import IdentityApi
from app.modules.jobs.application.feed import JobCard
from app.modules.jobs.application.photos import THUMB, photos_of
from app.modules.jobs.application.ports import JobQueries
from app.modules.media.api import MediaApi
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ListSavedJobsCommand:
    actor_id: UserId


class ListSavedJobs:
    def __init__(
        self, queries: JobQueries, media: MediaApi, identity: IdentityApi, clock: Clock
    ) -> None:
        self._queries, self._media, self._identity, self._clock = queries, media, identity, clock

    async def __call__(self, cmd: ListSavedJobsCommand) -> list[JobCard]:
        hidden = await self._identity.blocked_ids(cmd.actor_id)
        items = await self._queries.saved(
            cmd.actor_id, now=self._clock.now(), hidden_clients=hidden
        )
        wanted = {media_id for item in items for media_id in item.media_ids}
        refs = await self._media.refs(wanted) if wanted else {}
        return [JobCard(item=item, photos=photos_of(item.media_ids, refs, THUMB)) for item in items]
