"""Поправить шаблон отклика (PATCH /me/response-templates/{id}, S57; DEVELOPMENT_PLAN 5.5):
название и предложение — что прислано; «Сделать основным» ставит его первым, остальные — за
ним по прежнему порядку."""

from dataclasses import dataclass, replace

from app.modules.jobs.application.ports import ResponseTemplates
from app.modules.jobs.domain.response import Offer
from app.modules.jobs.domain.template import ResponseTemplate, TemplateId, template_title
from app.modules.jobs.errors import TemplateNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateTemplateCommand:
    actor_id: UserId
    template_id: TemplateId
    title: str | None = None
    offer: Offer | None = None
    primary: bool = False


class UpdateTemplate:
    def __init__(self, uow: UnitOfWork, templates: ResponseTemplates, clock: Clock) -> None:
        self._uow, self._templates, self._clock = uow, templates, clock

    async def __call__(self, cmd: UpdateTemplateCommand) -> ResponseTemplate:
        title = template_title(cmd.title) if cmd.title is not None else None
        now = self._clock.now()
        async with self._uow:
            await self._templates.lock(cmd.actor_id)
            templates = await self._templates.of_user(cmd.actor_id)
            target = next((t for t in templates if t.id == cmd.template_id), None)
            if target is None:
                raise TemplateNotFoundError(template_id=cmd.template_id)
            edited = replace(
                target,
                title=title or target.title,
                offer=cmd.offer or target.offer,
                updated_at=now,
            )
            others = [t for t in templates if t.id != target.id]
            order = (
                [edited, *others]
                if cmd.primary
                else [edited if t.id == target.id else t for t in templates]
            )
            result = edited
            for position, template in enumerate(order):
                if template.id == target.id:
                    result = replace(edited, position=position)
                    await self._templates.save(result)
                elif template.position != position:
                    await self._templates.save(replace(template, position=position, updated_at=now))
        return result
