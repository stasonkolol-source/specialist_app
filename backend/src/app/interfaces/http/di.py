"""Провайдер интерфейса web (ADR-0020 §7): Principal из Bearer JWT, локаль из Accept-Language.

Principal строится лениво — только для обработчиков, которые его просят: публичным
эндпоинтам (`/auth/refresh`) просроченный access не мешает. Токен проверяется подписью и
сроком, отозванная сессия (denylist Valkey) отвергается сразу.
"""

from dishka import Provider, Scope, provide
from fastapi import Request

from app.interfaces.http.client import DEFAULT_LOCALE
from app.platform.kernel.errors import NotAuthenticatedError
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Principal
from app.platform.observability.logging import bind_context
from app.platform.security.denylist import SessionDenylist
from app.platform.security.errors import SessionRevokedError
from app.platform.security.jwt import AccessTokens


def bearer_token(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise NotAuthenticatedError
    return token.strip()


class HttpProvider(Provider):
    @provide(scope=Scope.REQUEST)
    async def principal(
        self, request: Request, tokens: AccessTokens, denylist: SessionDenylist
    ) -> Principal:
        claims = tokens.decode(bearer_token(request))
        if await denylist.is_revoked(claims.session_id):
            raise SessionRevokedError
        principal = claims.principal()
        request.state.principal = principal
        bind_context(user_id=str(principal.user_id))
        return principal

    @provide(scope=Scope.REQUEST)
    def locale(self, request: Request) -> Locale:
        """Локаль ответа из Accept-Language (RequestContextMiddleware)."""
        locale = getattr(request.state, "locale", None)
        return locale if isinstance(locale, Locale) else DEFAULT_LOCALE
