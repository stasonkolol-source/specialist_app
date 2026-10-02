"""Отклик шаблоном в один тап (кнопка «Шаблон «…»» в уведомлении бота, DEVELOPMENT_PLAN 5.6 и
5.7): тот же Respond, что форма S16, — предложение из своего шаблона и его id. Шаблон удалили или он
чужой — 404 `response_template_not_found`.
"""

from dataclasses import dataclass

from app.modules.jobs.application.ports import ResponseTemplates
from app.modules.jobs.application.use_cases.respond import Respond, RespondCommand
from app.modules.jobs.domain.job import JobId
from app.modules.jobs.domain.response import ResponseId
from app.modules.jobs.domain.template import ResponseTemplate, TemplateId
from app.modules.jobs.errors import TemplateNotFoundError
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class RespondWithTemplateCommand:
    actor_id: UserId
    trust_level: int
    job_id: JobId
    template_id: TemplateId


class RespondWithTemplate:
    def __init__(self, respond: Respond, templates: ResponseTemplates) -> None:
        self._respond, self._templates = respond, templates

    async def __call__(
        self, cmd: RespondWithTemplateCommand
    ) -> tuple[ResponseTemplate, ResponseId]:
        mine = await self._templates.of_user(cmd.actor_id)
        template = next((item for item in mine if item.id == cmd.template_id), None)
        if template is None:
            raise TemplateNotFoundError(template_id=cmd.template_id)
        _, response_id = await self._respond(
            RespondCommand(
                actor_id=cmd.actor_id,
                trust_level=cmd.trust_level,
                job_id=cmd.job_id,
                offer=template.offer,
                template_id=template.id,
            )
        )
        return template, response_id
