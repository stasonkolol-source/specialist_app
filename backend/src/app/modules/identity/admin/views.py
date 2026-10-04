"""Разделы identity в админке (DEVELOPMENT_PLAN 2.7b): пользователи и санкции.

Только чтение строк; санкцию накладывают и снимают use cases (ADR-0020 §1) — действие раздела
«Снять» и страница «Наложить санкцию». Персональные данные (имя, телефон) раздел не показывает:
их видят support и admin в карточке Admin API `GET /admin/api/v1/users/{id}`, и каждый просмотр
пишется в audit_log (`identity.user.pii_viewed`, modules/identity/admin/router.py).
"""

from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID

from sqladmin import BaseView, action, expose
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.modules.identity.application.use_cases.impose_restriction import (
    ImposeRestriction,
    ImposeRestrictionCommand,
)
from app.modules.identity.application.use_cases.lift_restriction import (
    LiftRestriction,
    LiftRestrictionCommand,
)
from app.modules.identity.domain.restriction import RestrictionKind
from app.modules.identity.infrastructure.models import RestrictionRow, UserRow
from app.platform.http.admin import (
    MODERATION,
    SUPPORT,
    StaffModelView,
    run_action,
    staff_id,
    staff_roles,
)
from app.platform.kernel.clock import BUSINESS_TZ, ensure_utc
from app.platform.kernel.errors import DomainError
from app.platform.kernel.ids import RestrictionId, UserId


class UserAdmin(StaffModelView, model=UserRow):
    name = "Пользователь"
    name_plural = "Пользователи"
    icon = "fa-solid fa-user"
    category = "Пользователи"
    roles = SUPPORT
    audit_entity = "identity.user"
    can_create = can_edit = can_delete = False
    column_list: ClassVar[Any] = [
        UserRow.id,
        UserRow.status,
        UserRow.trust_level,
        UserRow.created_at,
        UserRow.last_seen_at,
    ]
    column_details_list: ClassVar[Any] = [
        UserRow.id,
        UserRow.status,
        UserRow.trust_level,
        UserRow.ui_locale,
        UserRow.home_city_id,
        UserRow.intent,
        UserRow.trust_penalty_at,
        UserRow.created_at,
        UserRow.last_seen_at,
        UserRow.deleted_at,
    ]
    column_searchable_list: ClassVar[Any] = [UserRow.id]
    column_default_sort: ClassVar[Any] = [(UserRow.created_at, True)]


class RestrictionAdmin(StaffModelView, model=RestrictionRow):
    name = "Санкция"
    name_plural = "Санкции"
    icon = "fa-solid fa-ban"
    category = "Пользователи"
    roles = MODERATION
    audit_entity = "identity.restriction"
    can_create = can_edit = can_delete = False
    column_list: ClassVar[Any] = [
        RestrictionRow.user_id,
        RestrictionRow.kind,
        RestrictionRow.reason_code,
        RestrictionRow.source,
        RestrictionRow.starts_at,
        RestrictionRow.ends_at,
        RestrictionRow.lifted_at,
    ]
    column_searchable_list: ClassVar[Any] = [RestrictionRow.user_id]
    column_default_sort: ClassVar[Any] = [(RestrictionRow.starts_at, True)]

    @action(
        name="lift",
        label="Снять",
        confirmation_message="Снять выбранные санкции? Действие попадёт в журнал аудита.",
    )
    async def lift(self, request: Request) -> Response:
        for pk in _pks(request):
            await run_action(
                request,
                LiftRestriction,
                LiftRestrictionCommand(
                    restriction_id=RestrictionId(UUID(pk)), staff_id=staff_id(request)
                ),
            )
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), 302)


class ImposeRestrictionView(BaseView):
    """Санкция пользователю — тем же путём, что решение модерации (фасад identity)."""

    name = "Наложить санкцию"
    icon = "fa-solid fa-gavel"
    category = "Пользователи"
    identity = "impose-restriction"

    def is_accessible(self, request: Request) -> bool:
        return bool(staff_roles(request) & MODERATION)

    def is_visible(self, request: Request) -> bool:
        return self.is_accessible(request)

    @expose("/impose-restriction", methods=["GET", "POST"])
    async def impose(self, request: Request) -> Response:
        context: dict[str, object] = {"kinds": [kind.value for kind in RestrictionKind]}
        if request.method == "POST":
            form = await request.form()
            context["form"] = dict(form)
            try:
                ends = str(form.get("ends_at", "")).strip()
                restriction_id = await run_action(
                    request,
                    ImposeRestriction,
                    ImposeRestrictionCommand(
                        user_id=UserId(UUID(str(form.get("user_id", "")).strip())),
                        kind=RestrictionKind(str(form.get("kind", ""))),
                        reason_code=str(form.get("reason_code", "")).strip(),
                        ends_at=_moment(ends) if ends else None,
                        staff_id=staff_id(request),
                    ),
                )
            except (ValueError, DomainError) as error:
                context["error"] = getattr(error, "code", None) or str(error)
            else:
                context["done"] = str(restriction_id)
        return await self._admin_ref.templates.TemplateResponse(
            request, "admin/impose_restriction.html", context
        )


def _moment(raw: str) -> datetime:
    """Время из формы: без пояса — по Белграду (datetime-local браузера)."""
    value = datetime.fromisoformat(raw)
    return ensure_utc(value if value.tzinfo else value.replace(tzinfo=BUSINESS_TZ))


def _pks(request: Request) -> list[str]:
    return [pk for pk in request.query_params.get("pks", "").split(",") if pk]


VIEWS = (UserAdmin, RestrictionAdmin, ImposeRestrictionView)
