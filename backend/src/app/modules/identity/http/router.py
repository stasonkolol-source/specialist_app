"""HTTP identity: вход, сессии, свой профиль и согласия (ARCHITECTURE §8.2, §8.5).

Тонкие обработчики: разобрать запрос, вызвать use case, собрать ответ. initData
проверяется здесь, на границе: в use case приходит уже проверенный профиль Telegram.
"""

import ipaddress
from typing import Annotated
from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Depends, Header, Request, Response, status

from app.modules.identity.application.access import AccessChecker
from app.modules.identity.application.dto import TelegramProfile
from app.modules.identity.application.ports import IdentityQuery
from app.modules.identity.application.use_cases.accept_consents import (
    AcceptConsents,
    AcceptConsentsCommand,
)
from app.modules.identity.application.use_cases.authenticate_telegram import (
    AuthenticateTelegram,
    AuthenticateTelegramCommand,
)
from app.modules.identity.application.use_cases.logout import Logout, LogoutCommand
from app.modules.identity.application.use_cases.refresh_session import (
    RefreshSession,
    RefreshSessionCommand,
)
from app.modules.identity.application.use_cases.update_profile import (
    UpdateProfile,
    UpdateProfileCommand,
)
from app.modules.identity.domain.session import SessionId
from app.modules.identity.errors import UserNotFoundError
from app.modules.identity.http.schemas import (
    AuthOut,
    ConsentsIn,
    MeOut,
    MeUpdateIn,
    RefreshIn,
    TokensOut,
)
from app.platform.http.concurrency import IfMatch, set_etag
from app.platform.http.ratelimit import RateLimit, client_ip
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.errors import NotAuthenticatedError
from app.platform.kernel.ids import CityId, UserId
from app.platform.kernel.principal import Principal
from app.platform.ratelimit import Rate, RateLimiter
from app.platform.security.errors import InvalidInitDataError
from app.platform.security.initdata import InitDataVerifier

AUTH_PER_IP = Rate("auth.ip", "10/minute")
AUTH_PER_TELEGRAM_USER = Rate("auth.telegram_user", "30/hour")
"""Лимиты /auth/* (ADR-0009, ARCHITECTURE §13.3)."""

router = APIRouter(tags=["identity"])
auth_limit = [Depends(RateLimit(AUTH_PER_IP, key=client_ip))]


def init_data_of(authorization: str | None) -> str:
    """`Authorization: tma <initData>` — формат @telegram-apps (ADR-0009)."""
    scheme, _, value = (authorization or "").partition(" ")
    if scheme.lower() != "tma" or not value.strip():
        raise InvalidInitDataError
    return value.strip()


@router.post("/auth/telegram", dependencies=auth_limit)
@inject
async def authenticate_telegram(
    verifier: FromDishka[InitDataVerifier],
    limiter: FromDishka[RateLimiter],
    authenticate: FromDishka[AuthenticateTelegram],
    query: FromDishka[IdentityQuery],
    access: FromDishka[AccessChecker],
    authorization: Annotated[str | None, Header(description="tma <initData>")] = None,
) -> AuthOut:
    """Обмен initData Mini App на собственную сессию.

    `start_param` из initData (код `startapp`) — первое касание: у нового пользователя
    он попадает в атрибуцию (growth), вернувшемуся не нужен.
    """
    init_data = verifier.verify(init_data_of(authorization))
    user = init_data.user
    await limiter.hit(AUTH_PER_TELEGRAM_USER, f"tg:{user.id}")
    profile = TelegramProfile(
        id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        language_code=user.language_code,
        is_premium=user.is_premium,
        allows_write_to_pm=user.allows_write_to_pm,
        photo_url=user.photo_url,
    )
    result = await authenticate(
        AuthenticateTelegramCommand(profile=profile, start_param=init_data.start_param)
    )
    me = await _me(query, access, result.tokens.user_id)
    return AuthOut(**TokensOut.of(result.tokens).model_dump(), is_new=result.is_new, user=me)


@router.post("/auth/refresh", dependencies=auth_limit)
@inject
async def refresh_session(body: RefreshIn, refresh: FromDishka[RefreshSession]) -> TokensOut:
    """Новая пара токенов; старый refresh больше не действует."""
    return TokensOut.of(await refresh(RefreshSessionCommand(refresh_token=body.refresh_token)))


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=AUTHENTICATED)
@inject
async def logout(principal: FromDishka[Principal], logout: FromDishka[Logout]) -> None:
    """Отозвать текущую сессию: refresh и выданные access перестают действовать."""
    if principal.session_id is None:
        raise NotAuthenticatedError
    session_id = SessionId(UUID(hex=principal.session_id))
    await logout(LogoutCommand(actor_id=principal.user_id, session_id=session_id))


@router.get("/me", dependencies=AUTHENTICATED)
@inject
async def get_me(
    principal: FromDishka[Principal],
    query: FromDishka[IdentityQuery],
    access: FromDishka[AccessChecker],
    response: Response,
) -> MeOut:
    """Профиль, принятые версии документов и что можно делать (онбординг, S49b)."""
    return await _me(query, access, principal.user_id, response)


@router.patch("/me", dependencies=AUTHENTICATED)
@inject
async def update_me(
    body: MeUpdateIn,
    expected_version: IfMatch,
    principal: FromDishka[Principal],
    update: FromDishka[UpdateProfile],
    query: FromDishka[IdentityQuery],
    access: FromDishka[AccessChecker],
    response: Response,
) -> MeOut:
    """Имя, язык, город и намерение. `If-Match: "<version>"` из ETag защищает от затирания."""
    await update(
        UpdateProfileCommand(
            actor_id=principal.user_id,
            display_name=body.display_name,
            ui_locale=body.ui_locale,
            home_city_id=CityId(body.home_city_id) if body.home_city_id is not None else None,
            intent=body.intent,
            expected_version=expected_version,
        )
    )
    return await _me(query, access, principal.user_id, response)


@router.post("/me/consents", dependencies=AUTHENTICATED)
@inject
async def accept_consents(
    body: ConsentsIn,
    request: Request,
    principal: FromDishka[Principal],
    accept: FromDishka[AcceptConsents],
    query: FromDishka[IdentityQuery],
    access: FromDishka[AccessChecker],
    response: Response,
) -> MeOut:
    """Одна галочка S02c: правила площадки (с 18+) и политика в версиях из client-config.

    Повтор идемпотентен; не та версия — 409 `legal_version_outdated`.
    """
    await accept(
        AcceptConsentsCommand(
            actor_id=principal.user_id,
            terms_version=body.terms_version,
            privacy_version=body.privacy_version,
            source=principal.platform,
            ip=_ip(request),
        )
    )
    return await _me(query, access, principal.user_id, response)


async def _me(
    query: IdentityQuery,
    access: AccessChecker,
    user_id: UserId,
    response: Response | None = None,
) -> MeOut:
    me = await query.me(user_id)
    if me is None:
        raise UserNotFoundError(user_id=user_id)
    if response is not None:
        set_etag(response, me.version)
    return MeOut.of(me, await access.view(user_id))


def _ip(request: Request) -> str | None:
    """Адрес клиента для журнала согласий; не IP (тестовый клиент) — не пишем."""
    host = request.client.host if request.client else None
    try:
        return str(ipaddress.ip_address(host)) if host else None
    except ValueError:
        return None
