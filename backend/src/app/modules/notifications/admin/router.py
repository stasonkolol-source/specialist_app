"""Admin API рассылок (DEVELOPMENT_PLAN 2.7b, часть 2; ARCHITECTURE §8.5): только admin.

Те же use cases, что раздел «Рассылки» SQLAdmin (admin/views.py): черновик (CreateBroadcast),
тест себе (SendBroadcastTest — мимо группы и тихих часов, в счётчики не входит), старт сейчас или
ко времени (StartBroadcast), отмена (CancelBroadcast); каждое действие пишет
`notifications.broadcast.*` в audit_log от имени сотрудника. Карточка — тексты, предпросмотр на
трёх языках тем же рендерером, что у получателей, и счётчики по доставкам. Отправка — очередь
`notifications` с приоритетом P4 и общий лимитер.
"""

from typing import Annotated, Final, Literal
from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Request, Response, status
from pydantic import AwareDatetime, BaseModel, Field

from app.modules.notifications.application.dto import BroadcastStats, BroadcastSummary
from app.modules.notifications.application.ports import BroadcastQuery, NotificationRenderer
from app.modules.notifications.application.use_cases.cancel_broadcast import (
    CancelBroadcast,
    CancelBroadcastCommand,
)
from app.modules.notifications.application.use_cases.create_broadcast import (
    CreateBroadcast,
    CreateBroadcastCommand,
)
from app.modules.notifications.application.use_cases.send_broadcast_test import (
    SendBroadcastTest,
    SendBroadcastTestCommand,
)
from app.modules.notifications.application.use_cases.start_broadcast import (
    StartBroadcast,
    StartBroadcastCommand,
)
from app.modules.notifications.domain.broadcast import Audience, BroadcastAction, BroadcastId
from app.modules.notifications.domain.catalog import EventGroup
from app.modules.notifications.errors import BroadcastNotFoundError
from app.platform.http.admin import ADMIN, INT4_MAX, INT4_MIN, staff_id
from app.platform.http.pagination import PageOut, PageParams
from app.platform.http.staff import staff_only
from app.platform.kernel.ids import CityId
from app.platform.kernel.localized import Locale
from app.platform.telegram.port import AppButton, CallbackButton

router = APIRouter(tags=["notifications"])

LOCALES: Final = (Locale.RU, Locale.SR_LATN, Locale.SR_CYRL)
MAX_TEXT = 3500
BroadcastGroup = Literal["marketing", "goods_launch"]


class BroadcastOut(BaseModel):
    id: UUID
    status: str = Field(description="draft → scheduled | sending → done | cancelled")
    group: str
    audience: str
    city_id: int | None
    text: dict[str, str]
    link: str | None
    action: str | None
    created_by: UUID
    created_at: AwareDatetime
    starts_at: AwareDatetime | None
    finished_at: AwareDatetime | None

    @classmethod
    def of(cls, item: BroadcastSummary) -> BroadcastOut:
        return cls(
            id=item.id,
            status=item.status,
            group=item.group,
            audience=item.audience,
            city_id=item.city_id,
            text=dict(item.text),
            link=item.link,
            action=item.action,
            created_by=item.created_by,
            created_at=item.created_at,
            starts_at=item.starts_at,
            finished_at=item.finished_at,
        )


class PreviewOut(BaseModel):
    locale: str
    text: str
    buttons: list[str]


class StatsOut(BaseModel):
    recipients: int
    queued: int
    deferred: int = Field(description="Из ждущих — до конца тихих часов или паузы лимитера")
    sent: int
    failed: int
    skipped: int

    @classmethod
    def of(cls, stats: BroadcastStats) -> StatsOut:
        return cls(
            recipients=stats.recipients,
            queued=stats.queued,
            deferred=stats.deferred,
            sent=stats.sent,
            failed=stats.failed,
            skipped=stats.skipped,
        )


class BroadcastCardOut(BaseModel):
    broadcast: BroadcastOut
    previews: list[PreviewOut]
    stats: StatsOut


class BroadcastIn(BaseModel):
    """Черновик: текст на русском и сербском (второй алфавит — по цепочке §7.4), без разметки."""

    text: dict[Locale, Annotated[str, Field(max_length=MAX_TEXT)]]
    group: BroadcastGroup = Field(
        default="marketing", description="Группа согласия S43: служебная рассылкам недоступна"
    )
    audience: Audience = Audience.ALL
    city_id: int | None = Field(default=None, ge=INT4_MIN, le=INT4_MAX)
    link: str | None = Field(
        default=None, max_length=64, description="Код deep link кнопки «Открыть «Соседи»»"
    )
    pro_waitlist: bool = Field(default=False, description="Кнопка «Хочу узнать первым»")


class BroadcastTestIn(BaseModel):
    locale: Locale = Locale.RU


class BroadcastStartIn(BaseModel):
    at: AwareDatetime | None = Field(
        default=None, description="Не раньше; null или прошлое — сейчас"
    )


class BroadcastStartedOut(BaseModel):
    status: str


class BroadcastCancelledOut(BaseModel):
    suppressed: int = Field(description="Сколько ждавших доставок погашено")


@router.get("/broadcasts", response_model=PageOut[BroadcastOut], **staff_only(ADMIN))
@inject
async def list_broadcasts(
    page: PageParams, query: FromDishka[BroadcastQuery]
) -> PageOut[BroadcastOut]:
    """Рассылки, новые первыми."""
    return PageOut.of(await query.recent(page), BroadcastOut.of)


@router.post(
    "/broadcasts",
    status_code=status.HTTP_201_CREATED,
    response_model=BroadcastCardOut,
    **staff_only(ADMIN),
)
@inject
async def create_broadcast(
    body: BroadcastIn,
    request: Request,
    create: FromDishka[CreateBroadcast],
    query: FromDishka[BroadcastQuery],
    renderer: FromDishka[NotificationRenderer],
) -> BroadcastCardOut:
    """Черновик рассылки; ответ — карточка с предпросмотром."""
    created = await create(
        CreateBroadcastCommand(
            staff_id=staff_id(request),
            text={locale.value: text for locale, text in body.text.items()},
            group=EventGroup(body.group),
            audience=body.audience,
            city_id=CityId(body.city_id) if body.city_id is not None else None,
            link=body.link,
            action=BroadcastAction.PRO_WAITLIST if body.pro_waitlist else None,
        )
    )
    return await _card(created, query, renderer)


@router.get("/broadcasts/{broadcast_id}", response_model=BroadcastCardOut, **staff_only(ADMIN))
@inject
async def get_broadcast(
    broadcast_id: UUID,
    query: FromDishka[BroadcastQuery],
    renderer: FromDishka[NotificationRenderer],
) -> BroadcastCardOut:
    """Тексты, предпросмотр на трёх языках (тем же рендерером, что у получателей) и счётчики."""
    return await _card(BroadcastId(broadcast_id), query, renderer)


@router.post(
    "/broadcasts/{broadcast_id}/test",
    status_code=status.HTTP_202_ACCEPTED,
    response_class=Response,
    **staff_only(ADMIN),
)
@inject
async def test_broadcast(
    broadcast_id: UUID, body: BroadcastTestIn, request: Request, send: FromDishka[SendBroadcastTest]
) -> Response:
    """Тест себе в бот на выбранном языке: мимо группы и тихих часов, в счётчики не входит."""
    await send(
        SendBroadcastTestCommand(
            staff_id=staff_id(request), broadcast_id=BroadcastId(broadcast_id), locale=body.locale
        )
    )
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/broadcasts/{broadcast_id}/start", response_model=BroadcastStartedOut, **staff_only(ADMIN)
)
@inject
async def start_broadcast(
    broadcast_id: UUID, body: BroadcastStartIn, request: Request, start: FromDishka[StartBroadcast]
) -> BroadcastStartedOut:
    """Старт сейчас (sending) или ко времени (scheduled)."""
    started = await start(
        StartBroadcastCommand(
            staff_id=staff_id(request), broadcast_id=BroadcastId(broadcast_id), at=body.at
        )
    )
    return BroadcastStartedOut(status=started.value)


@router.post(
    "/broadcasts/{broadcast_id}/cancel", response_model=BroadcastCancelledOut, **staff_only(ADMIN)
)
@inject
async def cancel_broadcast(
    broadcast_id: UUID, request: Request, cancel: FromDishka[CancelBroadcast]
) -> BroadcastCancelledOut:
    """Отмена: ждущие доставки гасятся в той же транзакции, следующая пачка видит отмену."""
    suppressed = await cancel(
        CancelBroadcastCommand(staff_id=staff_id(request), broadcast_id=BroadcastId(broadcast_id))
    )
    return BroadcastCancelledOut(suppressed=suppressed)


async def _card(
    broadcast_id: BroadcastId, query: BroadcastQuery, renderer: NotificationRenderer
) -> BroadcastCardOut:
    summary = await query.summary(broadcast_id)
    content = await query.content(broadcast_id)
    if summary is None or content is None:
        raise BroadcastNotFoundError(broadcast_id=broadcast_id)
    previews = []
    for locale in LOCALES:
        text, buttons = renderer.broadcast(content, locale)
        labels = [
            button.text for button in buttons if isinstance(button, AppButton | CallbackButton)
        ]
        previews.append(PreviewOut(locale=locale.value, text=text, buttons=labels))
    return BroadcastCardOut(
        broadcast=BroadcastOut.of(summary),
        previews=previews,
        stats=StatsOut.of(await query.stats(broadcast_id)),
    )
