"""Удалить шаблон отклика (DELETE /me/response-templates/{id}, S57; DEVELOPMENT_PLAN 5.5):
остальные сдвигаются — первый по порядку снова основной."""

from dataclasses import dataclass, replace

from app.modules.jobs.application.ports import ResponseTemplates
from app.modules.jobs.domain.template import TemplateId
from app.modules.jobs.errors import TemplateNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class DeleteTemplateCommand:
    actor_id: UserId
    template_id: TemplateId


class DeleteTemplate:
    def __init__(self, uow: UnitOfWork, templates: ResponseTemplates, clock: Clock) -> None:
        self._uow, self._templates, self._clock = uow, templates, clock

    async def __call__(self, cmd: DeleteTemplateCommand) -> None:
        now = self._clock.now()
        async with self._uow:
            await self._templates.lock(cmd.actor_id)
            templates = await self._templates.of_user(cmd.actor_id)
            if not any(t.id == cmd.template_id for t in templates):
                raise TemplateNotFoundError(template_id=cmd.template_id)
            await self._templates.delete(cmd.template_id, now=now)
            rest = [t for t in templates if t.id != cmd.template_id]
            for position, template in enumerate(rest):
                if template.position != position:
                    await self._templates.save(replace(template, position=position, updated_at=now))
