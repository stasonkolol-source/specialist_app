"""HTTP moderation, пользовательская часть (ARCHITECTURE §8.5; DEVELOPMENT_PLAN 4.7).

- `POST /reports` — жалоба (шторка S46): на профиль специалиста, заявку, отзыв, сообщение или
  собеседника; причина — из списка своего типа объекта. Жалоба — повод кейса P1 (угрозы и
  запрещённое — P0); повтор, пока кейс открыт, — та же жалоба (200), новая — 201. Двадцать
  первая за сутки — 429 `reports_limit`.

- `POST /appeals` — обжаловать решение (S49b «Обжаловать», 2.5b): кейс в очереди Appeals
  (≤ 72 ч). Апелляция на решение одна: новая — 201, повтор — та же (200, «уже обжаловано»).
  Нечего обжаловать — 404 `appeal_target_not_found`, прошло шесть месяцев — 409
  `appeal_window_closed`.

Кейсы решают кнопками карточки в чате модераторов (2.5b) и командами `cli moderation-decide`,
`cli dispute-resolve`; админка — 2.7b.
"""

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Response, status

from app.modules.moderation.application.use_cases.create_report import (
    CreateReport,
    CreateReportCommand,
)
from app.modules.moderation.application.use_cases.file_appeal import (
    FileAppeal,
    FileAppealCommand,
)
from app.modules.moderation.domain.cases import EntityType
from app.modules.moderation.http.schemas import AppealIn, AppealOut, ReportIn, ReportOut
from app.platform.contracts.events.identity import RestrictionKind
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.ids import CaseId
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


@router.post(
    "/appeals",
    status_code=status.HTTP_201_CREATED,
    response_model=AppealOut,
    responses={200: {"description": "Решение уже обжаловано: та же апелляция", "model": AppealOut}},
    dependencies=AUTHENTICATED,
)
@inject
async def file_appeal(
    body: AppealIn,
    response: Response,
    principal: FromDishka[Principal],
    file: FromDishka[FileAppeal],
) -> AppealOut:
    """Обжаловать решение модерации: апелляцию рассмотрит человек за 72 часа (S49b)."""
    filed = await file(
        FileAppealCommand(
            user_id=principal.user_id,
            case_id=CaseId(body.case_id) if body.case_id is not None else None,
            restriction=RestrictionKind(body.restriction) if body.restriction else None,
        )
    )
    if not filed.created:
        response.status_code = status.HTTP_200_OK
    return AppealOut.of(filed)
