"""HTTP портфолио `/me/profile/portfolio*` (S37, DEVELOPMENT_PLAN 2.11): работы — загруженные
файлы media с назначением portfolio, с подписью и порядком."""

from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, status

from app.modules.specialists.application.portfolio_views import PortfolioViews
from app.modules.specialists.application.use_cases.add_portfolio_work import (
    AddPortfolioWork,
    AddPortfolioWorkCommand,
)
from app.modules.specialists.application.use_cases.caption_portfolio_work import (
    CaptionPortfolioWork,
    CaptionPortfolioWorkCommand,
)
from app.modules.specialists.application.use_cases.remove_portfolio_work import (
    RemovePortfolioWork,
    RemovePortfolioWorkCommand,
)
from app.modules.specialists.application.use_cases.reorder_portfolio import (
    ReorderPortfolio,
    ReorderPortfolioCommand,
)
from app.modules.specialists.domain.portfolio import PortfolioItemId
from app.modules.specialists.errors import PortfolioItemNotFoundError, ProfileNotFoundError
from app.modules.specialists.http.schemas import (
    PortfolioLimitsOut,
    PortfolioOrderIn,
    PortfolioOut,
    WorkCaptionIn,
    WorkIn,
    WorkOut,
)
from app.platform.http.idempotency import idempotent_router
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.ids import MediaId, UserId
from app.platform.kernel.principal import Principal

portfolio = APIRouter(tags=["specialists"], dependencies=AUTHENTICATED)
adding = idempotent_router()


@portfolio.get("/me/profile/portfolio")
@inject
async def get_my_portfolio(
    principal: FromDishka[Principal], views: FromDishka[PortfolioViews]
) -> PortfolioOut:
    """Работы своего профиля по порядку (S37); 404 `profile_not_found` — профиля нет."""
    return await _portfolio(views, principal.user_id)


@adding.post("/me/profile/portfolio", status_code=status.HTTP_201_CREATED)
@inject
async def add_my_work(
    body: WorkIn,
    principal: FromDishka[Principal],
    add: FromDishka[AddPortfolioWork],
    views: FromDishka[PortfolioViews],
) -> WorkOut:
    """Работа из загруженного файла — в конец; лимит — 409 `portfolio_full` (kind, limit)."""
    item = await add(
        AddPortfolioWorkCommand(
            actor_id=principal.user_id, media_id=MediaId(body.media_id), caption=body.caption
        )
    )
    return await _work(views, principal.user_id, item.id)


@portfolio.put("/me/profile/portfolio/order")
@inject
async def reorder_my_portfolio(
    body: PortfolioOrderIn,
    principal: FromDishka[Principal],
    reorder: FromDishka[ReorderPortfolio],
    views: FromDishka[PortfolioViews],
) -> PortfolioOut:
    """Новый порядок — все работы; не те или не все — 422 `invalid_portfolio`."""
    await reorder(
        ReorderPortfolioCommand(
            actor_id=principal.user_id,
            item_ids=[PortfolioItemId(item_id) for item_id in body.item_ids],
        )
    )
    return await _portfolio(views, principal.user_id)


@portfolio.patch("/me/profile/portfolio/{item_id}")
@inject
async def caption_my_work(
    item_id: UUID,
    body: WorkCaptionIn,
    principal: FromDishka[Principal],
    caption: FromDishka[CaptionPortfolioWork],
    views: FromDishka[PortfolioViews],
) -> WorkOut:
    """Подпись работы; пустая — без подписи."""
    work_id = PortfolioItemId(item_id)
    await caption(
        CaptionPortfolioWorkCommand(
            actor_id=principal.user_id, item_id=work_id, caption=body.caption
        )
    )
    return await _work(views, principal.user_id, work_id)


@portfolio.delete("/me/profile/portfolio/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def remove_my_work(
    item_id: UUID, principal: FromDishka[Principal], remove: FromDishka[RemovePortfolioWork]
) -> None:
    """Убрать работу; её файл удаляется."""
    await remove(
        RemovePortfolioWorkCommand(actor_id=principal.user_id, item_id=PortfolioItemId(item_id))
    )


portfolio.include_router(adding)


async def _portfolio(views: PortfolioViews, user_id: UserId) -> PortfolioOut:
    works = await views.of_user(user_id)
    if works is None:
        raise ProfileNotFoundError(user_id=user_id)
    return PortfolioOut(
        items=[WorkOut.of(work) for work in works], limits=PortfolioLimitsOut.current()
    )


async def _work(views: PortfolioViews, user_id: UserId, item_id: PortfolioItemId) -> WorkOut:
    works = await views.of_user(user_id) or []
    work = next((work for work in works if work.id == item_id), None)
    if work is None:
        raise PortfolioItemNotFoundError(item_id=item_id)
    return WorkOut.of(work)
