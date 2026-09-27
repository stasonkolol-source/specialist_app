"""Схема Bearer для OpenAPI: замок у защищённых эндпоинтов и заголовок в api-client.

Проверку токена делает провайдер Principal (interfaces/http/di.py): обработчик, которому
нужен пользователь, просит `FromDishka[Principal]`. Эта зависимость ничего не проверяет.
"""

from fastapi import Depends
from fastapi.security import HTTPBearer

BEARER = HTTPBearer(auto_error=False, description="Access JWT из POST /auth/telegram")
AUTHENTICATED = [Depends(BEARER)]
"""`dependencies=AUTHENTICATED` у роутера или эндпоинта, которому нужен вход."""
