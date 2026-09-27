"""HTTP identity: вход, обновление сессии, выход, свой профиль (ARCHITECTURE §8.2, §8.5).

Тонкие обработчики: разобрать запрос, вызвать use case, собрать ответ. initData
проверяется здесь, на границе: в use case приходит уже проверенный профиль Telegram.
"""

from typing import Annotated
from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Depends, Header, Response, status

from app.modules.identity.application.dto import MeView, TelegramProfile
from app.modules.identity.application.ports import IdentityQuery
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
from app.modules.identity.http.schemas import AuthOut, MeOut, MeUpdateIn, RefreshIn, TokensOut
from app.platform.http.concurrency import IfMatch, set_etag
from app.platform.http.ratelimit import RateLimit, client_ip
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.errors import NotAuthenticatedError
from app.platform.kernel.ids import UserId
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
    authorization: Annotated[str | None, Header(description="tma <initData>")] = None,
) -> AuthOut:
    """Обмен initData Mini App на собственную сессию."""
    user = verifier.verify(init_data_of(authorization)).user
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
    result = await authenticate(AuthenticateTelegramCommand(profile=profile))
    me = await _me(query, result.tokens.user_id)
    return AuthOut(
        **TokensOut.of(result.tokens).model_dump(), is_new=result.is_new, user=MeOut.of(me)
    )


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
    principal: FromDishka[Principal], query: FromDishka[IdentityQuery], response: Response
) -> MeOut:
    me = await _me(query, principal.user_id)
    set_etag(response, me.version)
    return MeOut.of(me)


@router.patch("/me", dependencies=AUTHENTICATED)
@inject
async def update_me(
    body: MeUpdateIn,
    expected_version: IfMatch,
    principal: FromDishka[Principal],
    update: FromDishka[UpdateProfile],
    query: FromDishka[IdentityQuery],
    response: Response,
) -> MeOut:
    """Имя и язык интерфейса. `If-Match: "<version>"` из ETag защищает от затирания."""
    await update(
        UpdateProfileCommand(
            actor_id=principal.user_id,
            display_name=body.display_name,
            ui_locale=body.ui_locale,
            expected_version=expected_version,
        )
    )
    me = await _me(query, principal.user_id)
    set_etag(response, me.version)
    return MeOut.of(me)


async def _me(query: IdentityQuery, user_id: UserId) -> MeView:
    me = await query.me(user_id)
    if me is None:
        raise UserNotFoundError(user_id=user_id)
    return me
