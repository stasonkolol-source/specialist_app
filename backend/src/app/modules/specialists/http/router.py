"""HTTP кабинета исполнителя `/me/profile*` (ARCHITECTURE §8.5, DEVELOPMENT_PLAN 2.8a).

Тонкие обработчики: команда кабинета, затем свежий профиль из запроса и ETag с его версией.
`If-Match: "<version>"` защищает правки от затирания (412 при расхождении).
"""

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Response, status

from app.modules.specialists.application.ports import ProfileQuery
from app.modules.specialists.application.use_cases.become_pro import (
    BecomePro,
    BecomeProCommand,
)
from app.modules.specialists.application.use_cases.create_profile import (
    CreateProfile,
    CreateProfileCommand,
)
from app.modules.specialists.application.use_cases.edit_profile import (
    EditProfile,
    EditProfileCommand,
)
from app.modules.specialists.application.use_cases.hide_profile import (
    HideProfile,
    HideProfileCommand,
)
from app.modules.specialists.application.use_cases.set_profile_areas import (
    SetProfileAreas,
    SetProfileAreasCommand,
)
from app.modules.specialists.application.use_cases.set_profile_categories import (
    SetProfileCategories,
    SetProfileCategoriesCommand,
)
from app.modules.specialists.application.use_cases.show_profile import (
    ShowProfile,
    ShowProfileCommand,
)
from app.modules.specialists.application.use_cases.submit_profile import (
    SubmitProfile,
    SubmitProfileCommand,
)
from app.modules.specialists.errors import ProfileNotFoundError
from app.modules.specialists.http.schemas import (
    ProfileAreasIn,
    ProfileCategoriesIn,
    ProfileCreateIn,
    ProfileOut,
    ProfileUpdateIn,
)
from app.platform.http.concurrency import IfMatch, set_etag
from app.platform.http.idempotency import idempotent_router
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, UserId
from app.platform.kernel.principal import Principal

router = APIRouter(tags=["specialists"], dependencies=AUTHENTICATED)
creating = idempotent_router()


@router.get("/me/profile")
@inject
async def get_my_profile(
    principal: FromDishka[Principal], query: FromDishka[ProfileQuery], response: Response
) -> ProfileOut:
    """Свой профиль исполнителя (кабинет S33); 404 `profile_not_found` — профиля ещё нет."""
    return await _profile(query, principal.user_id, response)


@creating.post("/me/profile", status_code=status.HTTP_201_CREATED)
@inject
async def create_my_profile(
    body: ProfileCreateIn,
    principal: FromDishka[Principal],
    create: FromDishka[CreateProfile],
    query: FromDishka[ProfileQuery],
    response: Response,
) -> ProfileOut:
    """Начать профиль (S32a): «Специалист» или «Подработка» — черновик; 409 `profile_exists`."""
    await create(
        CreateProfileCommand(
            actor_id=principal.user_id,
            kind=body.kind,
            city_id=CityId(body.city_id),
            display_name=body.display_name,
        )
    )
    return await _profile(query, principal.user_id, response)


router.include_router(creating)


@router.patch("/me/profile")
@inject
async def update_my_profile(
    body: ProfileUpdateIn,
    expected_version: IfMatch,
    principal: FromDishka[Principal],
    edit: FromDishka[EditProfile],
    query: FromDishka[ProfileQuery],
    response: Response,
) -> ProfileOut:
    """Поля профиля (S32b–c, S34). Правки опубликованного — сразу, текст — на пост-модерацию."""
    await edit(
        EditProfileCommand(
            actor_id=principal.user_id,
            expected_version=expected_version,
            display_name=body.display_name,
            headline=body.headline,
            about=body.about,
            languages=body.languages,
            travel_radius_km=body.travel_radius_km,
            work_modes=body.work_modes,
        )
    )
    return await _profile(query, principal.user_id, response)


@router.put("/me/profile/categories")
@inject
async def set_my_categories(
    body: ProfileCategoriesIn,
    expected_version: IfMatch,
    principal: FromDishka[Principal],
    set_categories: FromDishka[SetProfileCategories],
    query: FromDishka[ProfileQuery],
    response: Response,
) -> ProfileOut:
    """Категории профиля целиком, первая — основная."""
    await set_categories(
        SetProfileCategoriesCommand(
            actor_id=principal.user_id,
            category_ids=[CategoryId(c) for c in body.category_ids],
            expected_version=expected_version,
        )
    )
    return await _profile(query, principal.user_id, response)


@router.put("/me/profile/areas")
@inject
async def set_my_areas(
    body: ProfileAreasIn,
    expected_version: IfMatch,
    principal: FromDishka[Principal],
    set_areas: FromDishka[SetProfileAreas],
    query: FromDishka[ProfileQuery],
    response: Response,
) -> ProfileOut:
    """Районы выезда целиком (районы города профиля)."""
    await set_areas(
        SetProfileAreasCommand(
            actor_id=principal.user_id,
            district_ids=[DistrictId(d) for d in body.district_ids],
            expected_version=expected_version,
        )
    )
    return await _profile(query, principal.user_id, response)


@router.post("/me/profile/submit")
@inject
async def submit_my_profile(
    expected_version: IfMatch,
    principal: FromDishka[Principal],
    submit: FromDishka[SubmitProfile],
    query: FromDishka[ProfileQuery],
    response: Response,
) -> ProfileOut:
    """На проверку (S32c «Отправить на проверку»); 409 `profile_incomplete` — чего не хватает."""
    await submit(
        SubmitProfileCommand(actor_id=principal.user_id, expected_version=expected_version)
    )
    return await _profile(query, principal.user_id, response)


@router.post("/me/profile/hide")
@inject
async def hide_my_profile(
    expected_version: IfMatch,
    principal: FromDishka[Principal],
    hide: FromDishka[HideProfile],
    query: FromDishka[ProfileQuery],
    response: Response,
) -> ProfileOut:
    """Скрыть опубликованный профиль из каталога."""
    await hide(HideProfileCommand(actor_id=principal.user_id, expected_version=expected_version))
    return await _profile(query, principal.user_id, response)


@router.post("/me/profile/show")
@inject
async def show_my_profile(
    expected_version: IfMatch,
    principal: FromDishka[Principal],
    show: FromDishka[ShowProfile],
    query: FromDishka[ProfileQuery],
    response: Response,
) -> ProfileOut:
    """Вернуть скрытый профиль в каталог."""
    await show(ShowProfileCommand(actor_id=principal.user_id, expected_version=expected_version))
    return await _profile(query, principal.user_id, response)


@router.post("/me/profile/become-pro")
@inject
async def become_pro(
    expected_version: IfMatch,
    principal: FromDishka[Principal],
    become: FromDishka[BecomePro],
    query: FromDishka[ProfileQuery],
    response: Response,
) -> ProfileOut:
    """«Подработка → Специалист»: профиль снова проверяет человек, потом он в каталоге."""
    await become(BecomeProCommand(actor_id=principal.user_id, expected_version=expected_version))
    return await _profile(query, principal.user_id, response)


async def _profile(query: ProfileQuery, user_id: UserId, response: Response) -> ProfileOut:
    view = await query.of_user(user_id)
    if view is None:
        raise ProfileNotFoundError(user_id=user_id)
    set_etag(response, view.version)
    return ProfileOut.of(view)
