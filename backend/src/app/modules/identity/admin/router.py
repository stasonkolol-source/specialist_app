"""Admin API identity (DEVELOPMENT_PLAN 2.7b; ARCHITECTURE §8.5, §13.2; ADR-0020 §1): карточка
пользователя и санкции.

- `GET /users/{id}` — support, moderator и admin. ПД (имя, телефон, Telegram) — только support и
  admin: каждый такой ответ пишет `identity.user.pii_viewed` в audit_log (InspectUser) и идёт в
  свой лимит просмотров; moderator получает карточку без ПД — для решения по кейсу их хватает.
- Санкции — moderator и admin, как в SQLAdmin: наложить (ImposeRestriction через фасад —
  UserRestricted, уровень доверия 0) и снять (LiftRestriction — UserRestrictionsLifted), оба — в
  аудит от имени сотрудника. Чужую санкцию по пути другого пользователя не снять — 404.
"""

from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Request, Response, status

from app.modules.identity.admin.schemas import RestrictionCreatedOut, RestrictionIn, UserCardOut
from app.modules.identity.application.use_cases.impose_restriction import (
    ImposeRestriction,
    ImposeRestrictionCommand,
)
from app.modules.identity.application.use_cases.inspect_user import (
    InspectUser,
    InspectUserCommand,
)
from app.modules.identity.application.use_cases.lift_restriction import (
    LiftRestriction,
    LiftRestrictionCommand,
)
from app.modules.identity.errors import RestrictionNotFoundError
from app.platform.http.admin import MODERATION, SUPPORT, staff_id, staff_roles
from app.platform.http.staff import PERSONAL_DATA, count_personal_data_view, staff_only
from app.platform.kernel.ids import CaseId, RestrictionId, UserId

router = APIRouter(tags=["identity"])


@router.get("/users/{user_id}", response_model=UserCardOut, **staff_only(SUPPORT))
@inject
async def get_user(
    user_id: UUID,
    request: Request,
    inspect: FromDishka[InspectUser],
    case_id: UUID | None = None,
) -> UserCardOut:
    """Карточка пользователя; `case_id` — по какому кейсу смотрят ПД (пишется в аудит)."""
    personal = bool(staff_roles(request) & PERSONAL_DATA)
    if personal:
        await count_personal_data_view(request)
    found = await inspect(
        InspectUserCommand(
            user_id=UserId(user_id),
            staff_id=staff_id(request),
            personal_data=personal,
            case_id=CaseId(case_id) if case_id is not None else None,
            ip=request.client.host if request.client else None,
        )
    )
    return UserCardOut.of(found)


@router.post(
    "/users/{user_id}/restrictions",
    status_code=status.HTTP_201_CREATED,
    response_model=RestrictionCreatedOut,
    **staff_only(MODERATION),
)
@inject
async def impose_restriction(
    user_id: UUID, body: RestrictionIn, request: Request, impose: FromDishka[ImposeRestriction]
) -> RestrictionCreatedOut:
    """Наложить санкцию: действует сразу; 422 invalid_restriction — код причины не машинный."""
    restriction_id = await impose(
        ImposeRestrictionCommand(
            user_id=UserId(user_id),
            kind=body.kind,
            reason_code=body.reason_code,
            ends_at=body.ends_at,
            staff_id=staff_id(request),
        )
    )
    return RestrictionCreatedOut(id=restriction_id)


@router.post(
    "/users/{user_id}/restrictions/{restriction_id}/lift",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    **staff_only(MODERATION),
)
@inject
async def lift_restriction(
    user_id: UUID, restriction_id: UUID, request: Request, lift: FromDishka[LiftRestriction]
) -> Response:
    """Снять санкцию пользователя; уже снятая или чужая — 404 restriction_not_found."""
    lifted = await lift(
        LiftRestrictionCommand(
            restriction_id=RestrictionId(restriction_id),
            staff_id=staff_id(request),
            user_id=UserId(user_id),
        )
    )
    if not lifted:
        raise RestrictionNotFoundError(restriction_id=restriction_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
