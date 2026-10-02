"""Шаблоны откликов исполнителя (GET /me/response-templates, S57 и S16; DEVELOPMENT_PLAN 5.5):
по порядку, первый — основной."""

from dataclasses import dataclass

from app.modules.jobs.application.ports import ResponseTemplates
from app.modules.jobs.domain.template import ResponseTemplate
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ListTemplatesCommand:
    actor_id: UserId


class ListTemplates:
    def __init__(self, uow: UnitOfWork, templates: ResponseTemplates) -> None:
        self._uow, self._templates = uow, templates

    async def __call__(self, cmd: ListTemplatesCommand) -> list[ResponseTemplate]:
        async with self._uow:
            return await self._templates.of_user(cmd.actor_id)
