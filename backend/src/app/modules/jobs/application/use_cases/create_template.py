"""Новый шаблон отклика (POST /me/response-templates, S57 и «сохранить как шаблон» на S16;
DEVELOPMENT_PLAN 5.5): не больше двух — третий 409 `response_templates_full`. Первый шаблон —
основной. Параллельные «Новый шаблон» сериализует блокировка пользователя."""

from dataclasses import dataclass

from app.modules.jobs.application.ports import ResponseTemplates
from app.modules.jobs.domain.response import Offer
from app.modules.jobs.domain.template import (
    MAX_TEMPLATES,
    ResponseTemplate,
    TemplateId,
    template_title,
)
from app.modules.jobs.errors import TemplatesFullError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId, new_id


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateTemplateCommand:
    actor_id: UserId
    title: str
    offer: Offer


class CreateTemplate:
    def __init__(self, uow: UnitOfWork, templates: ResponseTemplates, clock: Clock) -> None:
        self._uow, self._templates, self._clock = uow, templates, clock

    async def __call__(self, cmd: CreateTemplateCommand) -> ResponseTemplate:
        title = template_title(cmd.title)
        now = self._clock.now()
        async with self._uow:
            await self._templates.lock(cmd.actor_id)
            existing = await self._templates.of_user(cmd.actor_id)
            if len(existing) >= MAX_TEMPLATES:
                raise TemplatesFullError(limit=MAX_TEMPLATES)
            template = ResponseTemplate(
                id=TemplateId(new_id()),
                user_id=cmd.actor_id,
                title=title,
                offer=cmd.offer,
                position=len(existing),
                created_at=now,
                updated_at=now,
            )
            await self._templates.add(template)
        return template
