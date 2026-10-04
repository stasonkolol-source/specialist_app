"""Диспетчер бота (DEVELOPMENT_PLAN 0.22, 1.6, ADR-0011): роутеры модулей, общие команды,
dishka, FSM в Valkey."""

from collections.abc import Sequence
from typing import Final

from aiogram import Dispatcher, Router
from aiogram.fsm.storage.base import DefaultKeyBuilder
from aiogram.fsm.storage.redis import RedisStorage
from dishka import AsyncContainer
from dishka.integrations.aiogram import setup_dishka
from redis.asyncio import Redis

from app.interfaces.bot import commands
from app.interfaces.bot.middlewares import ErrorMiddleware, UserMiddleware

ALLOWED_UPDATES: Final = ("message", "callback_query", "my_chat_member")
"""Апдейты, которые бот просит у Telegram (polling и setWebhook): узкий список ADR-0011 — только
то, на что есть хендлеры. Остальное Telegram не присылает вовсе. Новый тип хендлера (оплата Stars,
inline-режим — v1) вписывается сюда; расхождение с хендлерами ловит тест."""


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
    # общие команды — после модулей: ответ на непонятное сообщение ловит только остаток
    dispatcher.include_router(commands.create_router())
    return dispatcher
