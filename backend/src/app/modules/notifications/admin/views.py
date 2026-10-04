"""Раздел «Рассылки» в админке (DEVELOPMENT_PLAN 2.7b, ARCHITECTURE §8.5 `/broadcasts`): admin.

Черновик, предпросмотр на каждом языке, тест себе, старт (сейчас или ко времени) и отмена — use
cases модуля (ADR-0020 §1), каждое действие пишет audit_log от имени сотрудника. Ход — счётчики
по доставкам: сколько получателей, ждут (из них — конца тихих часов), отправлено, ошибок,
пропущено по настройкам. Отправка — очередь `notifications` с приоритетом P4 и общий лимитер.
"""

from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqladmin import BaseView, expose
from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import Response

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
from app.modules.notifications.domain.catalog import BROADCAST_GROUPS, EventGroup
from app.modules.notifications.infrastructure.models import BroadcastRow
from app.platform.http.admin import ADMIN, container_of, run_action, staff_id, staff_roles
from app.platform.kernel.clock import BUSINESS_TZ
from app.platform.kernel.errors import DomainError
from app.platform.kernel.ids import CityId
from app.platform.kernel.localized import Locale
from app.platform.telegram.port import AppButton, CallbackButton

LOCALES: Final = (Locale.RU, Locale.SR_LATN, Locale.SR_CYRL)
RECENT: Final = 30


class BroadcastsView(BaseView):
    name = "Рассылки"
    icon = "fa-solid fa-bullhorn"
    identity = "broadcasts"

    def is_accessible(self, request: Request) -> bool:
        return bool(staff_roles(request) & ADMIN)

    def is_visible(self, request: Request) -> bool:
        return self.is_accessible(request)

    @expose("/broadcasts", methods=["GET", "POST"])
    async def broadcasts(self, request: Request) -> Response:
        source = await request.form() if request.method == "POST" else request.query_params
        context: dict[str, object] = {
            "groups": sorted(group.value for group in BROADCAST_GROUPS),
            "audiences": [audience.value for audience in Audience],
            "locales": [locale.value for locale in LOCALES],
        }
        selected = _uuid(source.get("id"))
        try:
            if request.method == "POST":
                selected = await self._act(request, source, selected, context)
        except DomainError as error:
            context["error"] = f"{error.code} {error.params}"
        except ValueError as error:  # неверное значение формы: город, дата, группа
            context["error"] = str(error)
        if selected is not None:
            await self._detail(request, BroadcastId(selected), context)
        context["recent"] = await self._recent()
        return await self._admin_ref.templates.TemplateResponse(
            request, "admin/broadcasts.html", context
        )

    async def _act(
        self, request: Request, source: Any, selected: UUID | None, context: dict[str, object]
    ) -> UUID | None:
        action = str(source.get("action", ""))
        staff = staff_id(request)
        if action == "create":
            city = str(source.get("city_id", "")).strip()
            link = str(source.get("link", "")).strip() or None
            created = await run_action(
                request,
                CreateBroadcast,
                CreateBroadcastCommand(
                    staff_id=staff,
                    text={
                        locale.value: str(source.get(f"text_{locale.value}", ""))
                        for locale in LOCALES
                    },
                    group=EventGroup(str(source.get("group", EventGroup.MARKETING.value))),
                    audience=Audience(str(source.get("audience", Audience.ALL.value))),
                    city_id=CityId(int(city)) if city else None,
                    link=link,
                    action=BroadcastAction.PRO_WAITLIST if source.get("waitlist") else None,
                ),
            )
            context["done"] = "Черновик создан"
            return created
        if selected is None:
            raise ValueError("Не выбрана рассылка")
        broadcast_id = BroadcastId(selected)
        if action == "test":
            await run_action(
                request,
                SendBroadcastTest,
                SendBroadcastTestCommand(
                    staff_id=staff,
                    broadcast_id=broadcast_id,
                    locale=Locale(str(source.get("locale", Locale.RU.value))),
                ),
            )
            context["done"] = "Тест поставлен в очередь: сообщение придёт вам в бот"
        elif action == "start":
            raw = str(source.get("at", "")).strip()
            at = datetime.fromisoformat(raw).replace(tzinfo=BUSINESS_TZ) if raw else None
            status = await run_action(
                request,
                StartBroadcast,
                StartBroadcastCommand(staff_id=staff, broadcast_id=broadcast_id, at=at),
            )
            context["done"] = f"Рассылка: {status.value}"
        elif action == "cancel":
            suppressed = await run_action(
                request,
                CancelBroadcast,
                CancelBroadcastCommand(staff_id=staff, broadcast_id=broadcast_id),
            )
            context["done"] = f"Рассылка отменена, не отправлено ждавших: {suppressed}"
        return selected

    async def _detail(
        self, request: Request, broadcast_id: BroadcastId, context: dict[str, object]
    ) -> None:
        container = container_of(request)
        query = await container.get(BroadcastQuery)
        content = await query.content(broadcast_id)
        if content is None:
            context["error"] = "broadcast_not_found"
            return
        renderer = await container.get(NotificationRenderer)
        previews = []
        for locale in LOCALES:
            text, buttons = renderer.broadcast(content, locale)
            labels = [
                button.text for button in buttons if isinstance(button, AppButton | CallbackButton)
            ]
            previews.append({"locale": locale.value, "text": text, "buttons": labels})
        context["selected"] = content
        context["previews"] = previews
        context["stats"] = await query.stats(broadcast_id)

    async def _recent(self) -> list[BroadcastRow]:
        async with self._admin_ref.session_maker() as session:
            rows = await session.execute(
                select(BroadcastRow).order_by(BroadcastRow.created_at.desc()).limit(RECENT)
            )
            return list(rows.scalars())


def _uuid(raw: object) -> UUID | None:
    try:
        return UUID(str(raw)) if raw else None
    except ValueError:
        return None


VIEWS = (BroadcastsView,)
