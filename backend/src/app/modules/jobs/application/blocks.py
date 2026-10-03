"""Блокировки зрителя в ленте и списках заявок (DEVELOPMENT_PLAN 4.7): с кем у него блокировка в
любую сторону, тех заявок он не видит, на них не откликается и в их заявки не приглашается."""

from dataclasses import replace

from app.modules.identity.api import IdentityApi
from app.modules.jobs.application.feed import FeedFilters
from app.platform.kernel.ids import UserId


async def without_blocked(
    identity: IdentityApi, filters: FeedFilters, viewer_id: UserId | None
) -> FeedFilters:
    """Фильтры ленты без заявок тех, с кем у зрителя блокировка; гостю — как есть."""
    if viewer_id is None:
        return filters
    hidden = await identity.blocked_ids(viewer_id)
    return replace(filters, hidden_clients=tuple(hidden)) if hidden else filters
