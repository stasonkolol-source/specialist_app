"""«Мои отзывы» (GET /me/reviews?direction=received|written, S28; DEVELOPMENT_PLAN 7.2):
полученные — опубликованные обо мне, с моим ответом; написанные — мои в любом статусе, кроме
стёртых. С именем второй стороны (identity) и названием сделки (deals) — пачкой на страницу."""

from dataclasses import dataclass, field

from app.modules.deals.api import DealsApi
from app.modules.identity.api import IdentityApi
from app.modules.reviews.application.dto import ReviewsDirection, UserReview
from app.modules.reviews.application.ports import ReviewQueries
from app.platform.kernel.ids import DealId, UserId
from app.platform.kernel.pagination import Page, PageRequest


@dataclass(frozen=True, slots=True, kw_only=True)
class ListMyReviewsCommand:
    actor_id: UserId
    direction: ReviewsDirection
    page: PageRequest = field(default_factory=PageRequest)


@dataclass(frozen=True, slots=True, kw_only=True)
class MyReviewsPage:
    page: Page[UserReview]
    names: dict[UserId, str]
    """Имя второй стороны; аккаунт удалён — нет в словаре."""
    titles: dict[DealId, str]


class ListMyReviews:
    def __init__(self, queries: ReviewQueries, identity: IdentityApi, deals: DealsApi) -> None:
        self._queries, self._identity, self._deals = queries, identity, deals

    async def __call__(self, cmd: ListMyReviewsCommand) -> MyReviewsPage:
        page = await self._queries.of_user(cmd.actor_id, cmd.direction, cmd.page)
        users = await self._identity.users({item.counterpart_id for item in page.items})
        deals = await self._deals.deal_briefs(
            {item.deal_id for item in page.items if item.deal_id is not None}
        )
        return MyReviewsPage(
            page=page,
            names={
                user_id: user.display_name for user_id, user in users.items() if not user.is_deleted
            },
            titles={deal_id: deal.title for deal_id, deal in deals.items()},
        )
