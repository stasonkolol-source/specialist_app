"""HTTP moderation, пользовательская часть (ARCHITECTURE §8.5; DEVELOPMENT_PLAN 4.7).

- `POST /reports` — жалоба (шторка S46): на профиль специалиста, заявку, отзыв, сообщение или
  собеседника; причина — из списка своего типа объекта. Жалоба — повод кейса P1 (угрозы и
  запрещённое — P0); повтор, пока кейс открыт, — та же жалоба (200), новая — 201. Двадцать
  первая за сутки — 429 `reports_limit`.

Кейсы решают командами `cli moderation-queue` и `cli moderation-decide` (решение владельца
2026-10-01: чат модераторов 2.5b и админка 2.7b — до беты).
"""

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Response, status

from app.modules.moderation.application.use_cases.create_report import (
    CreateReport,
    CreateReportCommand,
)
from app.modules.moderation.domain.cases import EntityType
from app.modules.moderation.http.schemas import ReportIn, ReportOut
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.principal import Principal

router = APIRouter(tags=["moderation"])


@router.post(
    "/reports",
    status_code=status.HTTP_201_CREATED,
    response_model=ReportOut,
    responses={200: {"description": "Та же открытая жалоба: повтор", "model": ReportOut}},
    dependencies=AUTHENTICATED,
)
@inject
async def create_report(
    body: ReportIn,
    response: Response,
    principal: FromDishka[Principal],
    create: FromDishka[CreateReport],
) -> ReportOut:
    """Пожаловаться: кейс модерации об объекте; ответ — жалоба и её очередь (S46 «Готово»)."""
    filed = await create(
        CreateReportCommand(
            reporter_id=principal.user_id,
            target_type=EntityType(body.target_type),
            target_id=body.target_id,
            reason=body.reason,
            comment=body.comment,
            conversation_id=body.conversation_id,
        )
    )
    if not filed.created:
        response.status_code = status.HTTP_200_OK
    return ReportOut.of(filed)
