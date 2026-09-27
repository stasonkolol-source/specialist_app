"""Провайдер интерфейса web (ADR-0020 §7): Principal из JWT, локаль из Accept-Language.

Principal кладёт в request.state middleware аутентификации (шаг 0.15b); без него — 401.
"""

from dishka import Provider, Scope, provide
from fastapi import Request

from app.platform.kernel.errors import NotAuthenticatedError
from app.platform.kernel.principal import Principal


class HttpProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def principal(self, request: Request) -> Principal:
        principal = getattr(request.state, "principal", None)
        if not isinstance(principal, Principal):
            raise NotAuthenticatedError
        return principal
