"""Диспетчер бота (DEVELOPMENT_PLAN 0.22, ADR-0011): роутеры модулей, dishka, FSM в Valkey."""

from collections.abc import Sequence

from aiogram import Dispatcher, Router
from aiogram.fsm.storage.base import DefaultKeyBuilder
from aiogram.fsm.storage.redis import RedisStorage
from dishka import AsyncContainer
from dishka.integrations.aiogram import setup_dishka
from redis.asyncio import Redis

from app.interfaces.bot.middlewares import ErrorMiddleware, UserMiddleware


def create_dispatcher(
    container: AsyncContainer, valkey: Redis, routers: Sequence[Router]
) -> Dispatcher:
    storage = RedisStorage(valkey, key_builder=DefaultKeyBuilder(prefix="bot:fsm"))
    dispatcher = Dispatcher(storage=storage)
    setup_dishka(container, dispatcher)
    for observer in (dispatcher.message, dispatcher.callback_query):
        observer.outer_middleware(ErrorMiddleware())
        observer.outer_middleware(UserMiddleware())
    for router in routers:
        dispatcher.include_router(router)
    return dispatcher
