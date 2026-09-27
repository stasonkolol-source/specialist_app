"""Провайдер интерфейса bot (ADR-0020 §7): Principal по telegram_id через фасад identity.

До шага 0.15 и 0.22 Principal кладёт в данные middleware aiogram аутентифицирующая
прослойка бота; без неё — 401-эквивалент (сообщение «нужно открыть приложение»).
"""

from dishka import Provider, Scope, provide
from dishka.integrations.aiogram import AiogramMiddlewareData

from app.platform.kernel.errors import NotAuthenticatedError
from app.platform.kernel.principal import Principal


class BotProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def principal(self, data: AiogramMiddlewareData) -> Principal:
        principal = data.get("principal")
        if not isinstance(principal, Principal):
            raise NotAuthenticatedError
        return principal
