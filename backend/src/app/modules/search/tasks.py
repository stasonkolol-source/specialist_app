"""Задачи search (ADR-0020 §3; DEVELOPMENT_PLAN 4.1).

- Подписчики событий профиля, прайса, каталога, санкций, удаления и готового фото профиля —
  отмечают профили к пересборке read-model.
- `search.flush_index` — пересобрать отмеченные пачкой (одна ждущая задача на всех).
- `search.reindex_profiles` — отметить профили позже: конец срочной санкции автора.
- `search.reconcile_index` — ночью: сверка read-model с источником.
- `search.forget_favorites` — UserDeleted: избранное удалённого аккаунта (4.6).
- `search.response_time_stats` — раз в час: «Обычно отвечает за …» — медиана первого ответа в
  диалогах за 30 дней (6.3b).
"""

import structlog
from dishka import FromDishka

from app.modules.search.application.ports import (
    FLUSH_INDEX,
    FORGET_FAVORITES,
    ON_AVAILABILITY,
    ON_CATALOG,
    ON_MEDIA_READY,
    ON_PRICE_LIST,
    ON_PROFILE_DELETED,
    ON_PROFILE_HIDDEN,
    ON_PROFILE_PUBLISHED,
    ON_PROFILE_UPDATED,
    ON_USER_DELETED,
    ON_USER_LIFTED,
    ON_USER_RESTRICTED,
    REINDEX_PROFILES,
    FlushPayload,
    ReindexPayload,
)
from app.modules.search.application.use_cases.flush_index import FlushIndex, FlushIndexCommand
from app.modules.search.application.use_cases.forget_favorites import (
    ForgetFavorites,
    ForgetFavoritesCommand,
)
from app.modules.search.application.use_cases.mark_profiles import (
    MarkProfiles,
    MarkProfilesCommand,
)
from app.modules.search.application.use_cases.reconcile_index import (
    ReconcileIndex,
    ReconcileIndexCommand,
)
from app.modules.search.application.use_cases.refresh_response_times import (
    RefreshResponseTimes,
    RefreshResponseTimesCommand,
)
from app.platform.contracts.events.catalog import CatalogChanged
from app.platform.contracts.events.identity import (
    UserDeleted,
    UserRestricted,
    UserRestrictionsLifted,
)
from app.platform.contracts.events.media import MediaReady
from app.platform.contracts.events.pricing import PriceListChanged
from app.platform.contracts.events.specialists import (
    AvailabilityChanged,
    ProfileDeleted,
    ProfileHidden,
    ProfilePublished,
    ProfileUpdated,
)
from app.platform.queue.tasks import PeriodicRun, periodic, subscriber, task

log = structlog.get_logger(__name__)

AVATAR = "avatar"

type ProfileEvent = (
    ProfilePublished
    | ProfileUpdated
    | ProfileHidden
    | ProfileDeleted
    | AvailabilityChanged
    | PriceListChanged
)
type UserEvent = UserRestricted | UserRestrictionsLifted | UserDeleted


async def _profile(mark: MarkProfiles, event: ProfileEvent) -> None:
    await mark(MarkProfilesCommand(profile_ids=(event.profile_id,), occurred_at=event.occurred_at))


@subscriber(ProfilePublished, ON_PROFILE_PUBLISHED)
async def on_profile_published(event: ProfilePublished, mark: FromDishka[MarkProfiles]) -> None:
    await _profile(mark, event)


@subscriber(ProfileUpdated, ON_PROFILE_UPDATED)
async def on_profile_updated(event: ProfileUpdated, mark: FromDishka[MarkProfiles]) -> None:
    await _profile(mark, event)


@subscriber(ProfileHidden, ON_PROFILE_HIDDEN)
async def on_profile_hidden(event: ProfileHidden, mark: FromDishka[MarkProfiles]) -> None:
    await _profile(mark, event)


@subscriber(ProfileDeleted, ON_PROFILE_DELETED)
async def on_profile_deleted(event: ProfileDeleted, mark: FromDishka[MarkProfiles]) -> None:
    await _profile(mark, event)


@subscriber(AvailabilityChanged, ON_AVAILABILITY)
async def on_availability(event: AvailabilityChanged, mark: FromDishka[MarkProfiles]) -> None:
    await _profile(mark, event)


@subscriber(PriceListChanged, ON_PRICE_LIST)
async def on_price_list(event: PriceListChanged, mark: FromDishka[MarkProfiles]) -> None:
    await _profile(mark, event)


async def _user(mark: MarkProfiles, event: UserEvent) -> None:
    await mark(MarkProfilesCommand(user_ids=(event.user_id,), occurred_at=event.occurred_at))


@subscriber(UserRestricted, ON_USER_RESTRICTED)
async def on_user_restricted(event: UserRestricted, mark: FromDishka[MarkProfiles]) -> None:
    await _user(mark, event)


@subscriber(UserRestrictionsLifted, ON_USER_LIFTED)
async def on_user_lifted(event: UserRestrictionsLifted, mark: FromDishka[MarkProfiles]) -> None:
    await _user(mark, event)


@subscriber(UserDeleted, ON_USER_DELETED)
async def on_user_deleted(event: UserDeleted, mark: FromDishka[MarkProfiles]) -> None:
    await _user(mark, event)


@subscriber(UserDeleted, FORGET_FAVORITES)
async def forget_favorites(event: UserDeleted, forget: FromDishka[ForgetFavorites]) -> None:
    await forget(ForgetFavoritesCommand(user_id=event.user_id))


@subscriber(CatalogChanged, ON_CATALOG)
async def on_catalog(event: CatalogChanged, mark: FromDishka[MarkProfiles]) -> None:
    await mark(MarkProfilesCommand(category_ids=event.category_ids, occurred_at=event.occurred_at))


@subscriber(MediaReady, ON_MEDIA_READY)
async def on_media_ready(event: MediaReady, mark: FromDishka[MarkProfiles]) -> None:
    """Фото профиля обработано: в карточке вместо инициалов — фото."""
    if event.purpose == AVATAR:
        await mark(MarkProfilesCommand(user_ids=(event.owner_id,), occurred_at=event.occurred_at))


@task(FLUSH_INDEX)
async def flush_index(payload: FlushPayload, flush: FromDishka[FlushIndex]) -> None:
    report = await flush(FlushIndexCommand())
    if report.indexed or report.removed:
        log.info(
            "search_index_flushed",
            reason=payload.reason,
            indexed=report.indexed,
            removed=report.removed,
            more=report.more,
        )


@task(REINDEX_PROFILES)
async def reindex_profiles(payload: ReindexPayload, mark: FromDishka[MarkProfiles]) -> None:
    await mark(MarkProfilesCommand(profile_ids=payload.profile_ids))


@periodic("search.reconcile_index", cron="23 3 * * *")
async def reconcile_index(run: PeriodicRun) -> None:
    async with run.container() as request:
        reconcile = await request.get(ReconcileIndex)
        report = await reconcile(ReconcileIndexCommand())
    log.info("search_index_reconcile", published=report.published, indexed=report.indexed)


@periodic("search.response_time_stats", cron="31 * * * *")
async def response_time_stats(run: PeriodicRun) -> None:
    """Раз в час: «Обычно отвечает за …» по диалогам за 30 дней (6.3b)."""
    async with run.container() as request:
        refresh = await request.get(RefreshResponseTimes)
        counted = await refresh(RefreshResponseTimesCommand())
    log.info("search_response_times", specialists=counted)
