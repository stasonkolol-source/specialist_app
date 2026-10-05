"""HTTP deals (DEVELOPMENT_PLAN 6.1a; ARCHITECTURE §8.5, §7.9): сделка сторонам.

- `GET /me/deals?role=&status=` — свои сделки клиентом, исполнителем или все, новые первыми,
  курсор;
- `GET /deals/{id}` — сделка стороне (S26); не участник — 404;
- `POST /deals/{id}/confirm` — вторая сторона подтверждает «Договорились» из чата (S53, 6.3b);
- `POST /deals/{id}/decline` — отклонить «Договорились», пока предложение ждёт ответа (S53);
- `POST /deals/{id}/complete` — «Работа выполнена»: отметили обе — сделка завершена;
- `POST /deals/{id}/cancel` — отмена с причиной: заявка снова открыта, прежние кандидаты —
  «просмотрен» (§7.9);
- `POST /deals/{id}/dispute` — спор по идущей сделке (S52, 6.1c): кейс модерации, второй стороне
  48 ч на ответ; `…/dispute/respond` — её ответ, `…/dispute/withdraw` — отзыв спора открывшим.
  Ответ — спор стороне с фото по presigned GET приватного бакета.

Сделка из отклика создаётся в `POST /responses/{id}/accept` (jobs) — в той же транзакции.
"""

from typing import Annotated, Final
from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Path, Query, status

from app.modules.deals.application.use_cases.cancel_deal import CancelDeal, CancelDealCommand
from app.modules.deals.application.use_cases.complete_deal import (
    CompleteDeal,
    CompleteDealCommand,
)
from app.modules.deals.application.use_cases.confirm_deal import ConfirmDeal, ConfirmDealCommand
from app.modules.deals.application.use_cases.decline_deal import DeclineDeal, DeclineDealCommand
from app.modules.deals.application.use_cases.list_my_deals import (
    ListMyDeals,
    ListMyDealsCommand,
)
from app.modules.deals.application.use_cases.open_dispute import (
    OpenDispute,
    OpenDisputeCommand,
)
from app.modules.deals.application.use_cases.respond_dispute import (
    RespondDispute,
    RespondDisputeCommand,
)
from app.modules.deals.application.use_cases.show_deal import ShowDeal, ShowDealCommand
from app.modules.deals.application.use_cases.show_dispute import (
    ShowDispute,
    ShowDisputeCommand,
)
from app.modules.deals.application.use_cases.withdraw_dispute import (
    WithdrawDispute,
    WithdrawDisputeCommand,
)
from app.modules.deals.domain.deal import DealRole, DealStatus
from app.modules.deals.domain.dispute import DisputeId
from app.modules.deals.http.schemas import (
    DealCancelIn,
    DealOut,
    DealsPageOut,
    DisputeAnswerIn,
    DisputeIn,
    DisputeOut,
)
from app.modules.media.api import MediaApi
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.ids import DealId, UserId
from app.platform.kernel.pagination import DEFAULT_LIMIT, PageRequest
from app.platform.kernel.principal import Principal

MY_DEALS_LIMIT: Final = 50

router = APIRouter(tags=["deals"])
DealPath = Annotated[UUID, Path(description="id сделки")]


@router.get("/me/deals", response_model=DealsPageOut, dependencies=AUTHENTICATED)
@inject
async def list_my_deals(
    *,
    role: Annotated[
        DealRole | None, Query(description="client или performer; без него — все")
    ] = None,
    statuses: Annotated[
        list[DealStatus] | None, Query(alias="status", description="Без фильтра — все")
    ] = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=MY_DEALS_LIMIT)] = DEFAULT_LIMIT,
    principal: FromDishka[Principal],
    deals: FromDishka[ListMyDeals],
) -> DealsPageOut:
    """Свои сделки, новые первыми."""
    page = await deals(
        ListMyDealsCommand(
            actor_id=principal.user_id,
            role=role,
            statuses=statuses or [],
            page=PageRequest(cursor=cursor, limit=limit),
        )
    )
    return DealsPageOut(
        items=[DealOut.of(deal, principal.user_id) for deal in page.items],
        next_cursor=page.next_cursor,
    )


@router.get("/deals/{deal_id:uuid}", response_model=DealOut, dependencies=AUTHENTICATED)
@inject
async def get_deal(
    deal_id: DealPath, principal: FromDishka[Principal], show: FromDishka[ShowDeal]
) -> DealOut:
    """Сделка стороне (S26); не участник — 404."""
    return await _shown(show, principal.user_id, DealId(deal_id))


@router.post("/deals/{deal_id:uuid}/confirm", response_model=DealOut, dependencies=AUTHENTICATED)
@inject
async def confirm_deal(
    deal_id: DealPath,
    principal: FromDishka[Principal],
    confirm: FromDishka[ConfirmDeal],
    show: FromDishka[ShowDeal],
) -> DealOut:
    """Подтвердить «Договорились» второй стороной: сделка `agreed`. Предложившему — 409."""
    await confirm(ConfirmDealCommand(actor_id=principal.user_id, deal_id=DealId(deal_id)))
    return await _shown(show, principal.user_id, DealId(deal_id))


@router.post("/deals/{deal_id:uuid}/decline", response_model=DealOut, dependencies=AUTHENTICATED)
@inject
async def decline_deal(
    deal_id: DealPath,
    principal: FromDishka[Principal],
    decline: FromDishka[DeclineDeal],
    show: FromDishka[ShowDeal],
) -> DealOut:
    """Отклонить «Договорились» (S53): только пока предложение ждёт ответа, иначе 409."""
    await decline(DeclineDealCommand(actor_id=principal.user_id, deal_id=DealId(deal_id)))
    return await _shown(show, principal.user_id, DealId(deal_id))


@router.post("/deals/{deal_id:uuid}/complete", response_model=DealOut, dependencies=AUTHENTICATED)
@inject
async def complete_deal(
    deal_id: DealPath,
    principal: FromDishka[Principal],
    complete: FromDishka[CompleteDeal],
    show: FromDishka[ShowDeal],
) -> DealOut:
    """«Работа выполнена»: отметка стороны, повтор — без изменений; отметили обе —
    `completed`."""
    await complete(CompleteDealCommand(actor_id=principal.user_id, deal_id=DealId(deal_id)))
    return await _shown(show, principal.user_id, DealId(deal_id))


@router.post("/deals/{deal_id:uuid}/cancel", response_model=DealOut, dependencies=AUTHENTICATED)
@inject
async def cancel_deal(
    deal_id: DealPath,
    body: DealCancelIn,
    principal: FromDishka[Principal],
    cancel: FromDishka[CancelDeal],
    show: FromDishka[ShowDeal],
) -> DealOut:
    """Отменить сделку или предложение «Договорились» с причиной."""
    await cancel(
        CancelDealCommand(
            actor_id=principal.user_id, deal_id=DealId(deal_id), reason=body.cancel_reason()
        )
    )
    return await _shown(show, principal.user_id, DealId(deal_id))


@router.post(
    "/deals/{deal_id:uuid}/dispute",
    response_model=DisputeOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=AUTHENTICATED,
)
@inject
async def open_dispute(
    deal_id: DealPath,
    body: DisputeIn,
    principal: FromDishka[Principal],
    open_: FromDishka[OpenDispute],
    show: FromDishka[ShowDispute],
    media: FromDishka[MediaApi],
) -> DisputeOut:
    """Спор по идущей сделке (S52): сделка `disputed`, второй стороне 48 ч на ответ. Сделка не
    `agreed` — 409 `deal_not_active`; фото не свои или не `dispute` — 404 / 409."""
    dispute_id = await open_(
        OpenDisputeCommand(
            actor_id=principal.user_id,
            deal_id=DealId(deal_id),
            kind=body.kind,
            description=body.description,
            media_ids=body.photos(),
        )
    )
    return await _dispute(show, media, principal.user_id, dispute_id)


@router.post(
    "/deals/{deal_id:uuid}/dispute/respond",
    response_model=DisputeOut,
    dependencies=AUTHENTICATED,
)
@inject
async def respond_dispute(
    deal_id: DealPath,
    body: DisputeAnswerIn,
    principal: FromDishka[Principal],
    respond: FromDishka[RespondDispute],
    show: FromDishka[ShowDispute],
    media: FromDishka[MediaApi],
) -> DisputeOut:
    """Ответ второй стороны — один, пока модератор не решил; иначе 409
    `dispute_state_conflict`. Идущего спора нет — 404 `dispute_not_found`."""
    dispute_id = await respond(
        RespondDisputeCommand(
            actor_id=principal.user_id,
            deal_id=DealId(deal_id),
            text=body.text,
            media_ids=body.photos(),
        )
    )
    return await _dispute(show, media, principal.user_id, dispute_id)


@router.post(
    "/deals/{deal_id:uuid}/dispute/withdraw",
    response_model=DisputeOut,
    dependencies=AUTHENTICATED,
)
@inject
async def withdraw_dispute(
    deal_id: DealPath,
    principal: FromDishka[Principal],
    withdraw: FromDishka[WithdrawDispute],
    show: FromDishka[ShowDispute],
    media: FromDishka[MediaApi],
) -> DisputeOut:
    """Отозвать свой спор, пока модератор не решил: сделка снова идёт."""
    dispute_id = await withdraw(
        WithdrawDisputeCommand(actor_id=principal.user_id, deal_id=DealId(deal_id))
    )
    return await _dispute(show, media, principal.user_id, dispute_id)


async def _dispute(
    show: ShowDispute, media: MediaApi, viewer_id: UserId, dispute_id: DisputeId
) -> DisputeOut:
    dispute, deal_status = await show(ShowDisputeCommand(actor_id=viewer_id, dispute_id=dispute_id))
    refs = await media.refs([*dispute.media_ids, *dispute.response_media_ids])
    return DisputeOut.of(dispute, viewer_id, deal_status=deal_status, refs=refs)


async def _shown(show: ShowDeal, viewer_id: UserId, deal_id: DealId) -> DealOut:
    return DealOut.of(await show(ShowDealCommand(actor_id=viewer_id, deal_id=deal_id)), viewer_id)
