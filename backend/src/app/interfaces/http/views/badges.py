"""BFF бейджей таббара (DEVELOPMENT_PLAN 6.4; ARCHITECTURE §8.5): «Заявки N» — новые отклики на свои
открытые заявки (jobs), «Сообщения N» — непрочитанные сообщения во всех диалогах (messaging).
Приложение спрашивает при открытии и при возврате на вкладку; ответ — без кэша.
"""

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from app.modules.jobs.api import JobsApi
from app.modules.messaging.api import MessagingApi
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.principal import Principal

router = APIRouter(tags=["views"])


class BadgesOut(BaseModel):
    jobs: int = Field(description="«Заявки N»: новые отклики на свои открытые заявки")
    messages: int = Field(description="«Сообщения N»: непрочитанные сообщения")


@router.get("/me/badges", response_model=BadgesOut, dependencies=AUTHENTICATED)
@inject
async def get_badges(
    principal: FromDishka[Principal],
    jobs: FromDishka[JobsApi],
    messaging: FromDishka[MessagingApi],
    response: Response,
) -> BadgesOut:
    """Счётчики таббара: новые отклики и непрочитанные сообщения."""
    response.headers["Cache-Control"] = "private, no-store"
    return BadgesOut(
        jobs=await jobs.unseen_responses(principal.user_id),
        messages=await messaging.unread_total(principal.user_id),
    )
