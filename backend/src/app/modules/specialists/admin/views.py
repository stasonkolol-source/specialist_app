"""Профили исполнителей в админке (DEVELOPMENT_PLAN 2.7b; §15.2, ADR-0014, ADR-0020 §1).

Только чтение строк: профиль — агрегат с инвариантами, его меняют use cases. Действия раздела
«Отметить Founding» и «Снять Founding» — use case SetFounding от имени сотрудника, с записью в
audit_log (то же, что `cli founding-mark`, но по строке профиля и с отменой ошибочной отметки).
Имя, описание и контакты раздел не показывает: просмотр ПД с записью в аудит — карточкой
пользователя Admin API (2.7b, дальше). Удалённые профили в списке не видны.
"""

from typing import Any, ClassVar
from uuid import UUID

from sqladmin import action
from sqlalchemy import Select, func, select
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.modules.specialists.application.use_cases.mark_founding import (
    SetFounding,
    SetFoundingCommand,
)
from app.modules.specialists.domain.profile import ProfileId
from app.modules.specialists.infrastructure.models import ProfileRow
from app.platform.http.admin import ADMIN, StaffModelView, run_action, staff_id
from app.platform.kernel.errors import DomainError


class ProfileAdmin(StaffModelView, model=ProfileRow):
    name = "Профиль исполнителя"
    name_plural = "Профили исполнителей"
    icon = "fa-solid fa-user-tie"
    category = "Пользователи"
    roles = ADMIN
    audit_entity = "specialists.profile"
    can_create = can_edit = can_delete = False
    column_list: ClassVar[Any] = [
        ProfileRow.id,
        ProfileRow.user_id,
        ProfileRow.kind,
        ProfileRow.status,
        ProfileRow.is_founding,
        ProfileRow.city_id,
        ProfileRow.published_at,
        ProfileRow.created_at,
    ]
    column_details_list: ClassVar[Any] = column_list
    column_labels: ClassVar[Any] = {ProfileRow.is_founding: "Founding"}
    column_searchable_list: ClassVar[Any] = [ProfileRow.id, ProfileRow.user_id]
    column_sortable_list: ClassVar[Any] = [ProfileRow.created_at, ProfileRow.published_at]
    column_default_sort: ClassVar[Any] = [(ProfileRow.created_at, True)]
    help_text = (
        "Founding — первые 150–200 специалистов (§15.2): флаг профиля, в MVP без бейджа;"
        " бейдж и бесплатный Pro — v1. Выберите профили и действие «Отметить Founding» или"
        " «Снять Founding»: каждая смена попадает в журнал аудита."
    )

    def list_query(self, request: Request) -> Select[Any]:  # noqa: ARG002
        return select(ProfileRow).where(ProfileRow.deleted_at.is_(None))

    def count_query(self, request: Request) -> Select[Any]:  # noqa: ARG002
        alive = ProfileRow.deleted_at.is_(None)
        return select(func.count()).select_from(ProfileRow).where(alive)

    @action(
        name="founding_on",
        label="Отметить Founding",
        confirmation_message="Отметить выбранные профили статусом Founding?",
    )
    async def founding_on(self, request: Request) -> Response:
        return await self._set(request, founding=True)

    @action(
        name="founding_off",
        label="Снять Founding",
        confirmation_message="Снять статус Founding с выбранных профилей?",
    )
    async def founding_off(self, request: Request) -> Response:
        return await self._set(request, founding=False)

    async def _set(self, request: Request, *, founding: bool) -> Response:
        for pk in [pk for pk in request.query_params.get("pks", "").split(",") if pk]:
            try:
                await run_action(
                    request,
                    SetFounding,
                    SetFoundingCommand(
                        profile_id=ProfileId(UUID(pk)),
                        founding=founding,
                        staff_id=staff_id(request),
                    ),
                )
            except ValueError, DomainError:
                continue  # профиль удалили, пока список был открыт: остальные — как обычно
        return RedirectResponse(request.url_for("admin:list", identity=self.identity), 302)


VIEWS = (ProfileAdmin,)
