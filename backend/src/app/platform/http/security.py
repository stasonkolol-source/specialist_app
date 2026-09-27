"""Вход для защищённых эндпоинтов: `dependencies=AUTHENTICATED` у роутера или маршрута.

Зависимость маршрута выполняется раньше разбора параметров и тела, поэтому запрос без
действующего токена получает 401, а не 422 о полях, которые ему всё равно нельзя
менять. Principal строит провайдер (interfaces/http/di.py) и кэширует в REQUEST scope:
обработчик получает тот же объект через `FromDishka[Principal]`. HTTPBearer здесь —
описание схемы для OpenAPI (замок у операции и заголовок в api-client).
"""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.platform.kernel.principal import Principal

BEARER = HTTPBearer(auto_error=False, description="Access JWT из POST /auth/telegram")


async def authenticated(
    request: Request,
    _credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(BEARER)],
) -> None:
    await request.state.dishka_container.get(Principal)


AUTHENTICATED = [Depends(authenticated)]
