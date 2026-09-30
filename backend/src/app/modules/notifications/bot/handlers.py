"""Бот notifications (DEVELOPMENT_PLAN 2.3b, ADR-0011): статус канала следует за человеком.

Остановил бота в личном чате (`my_chat_member` → `kicked`) — канал telegram выключается;
запустил снова (`member`) — включается, как после /start. Апдейт человека, которого нет
среди пользователей (ещё не нажал /start), ничего не меняет: канал появится с /start.
"""

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.types import ChatMemberUpdated
from dishka.integrations.aiogram import FromDishka, inject

from app.modules.identity.api import IdentityApi
from app.modules.notifications.application.use_cases.block_telegram_channel import (
    BlockTelegramChannel,
    BlockTelegramChannelCommand,
)
from app.modules.notifications.application.use_cases.grant_telegram_write_access import (
    GrantTelegramWriteAccess,
    GrantTelegramWriteAccessCommand,
)
from app.modules.notifications.domain.channel import GrantedVia


@inject
async def member_status(
    update: ChatMemberUpdated,
    identity: FromDishka[IdentityApi],
    block: FromDishka[BlockTelegramChannel],
    grant: FromDishka[GrantTelegramWriteAccess],
) -> None:
    if update.from_user.is_bot:
        return
    user = await identity.by_telegram(update.from_user.id)
    if user is None:
        return
    status = update.new_chat_member.status
    if status == ChatMemberStatus.KICKED:
        await block(BlockTelegramChannelCommand(user_id=user.id, at=update.date))
    elif status == ChatMemberStatus.MEMBER:
        await grant(
            GrantTelegramWriteAccessCommand(
                user_id=user.id, via=GrantedVia.BOT_START, at=update.date
            )
        )


def create_router() -> Router:
    """Новый роутер на каждый вызов: роутер aiogram подключается только к одному диспетчеру."""
    router = Router(name="notifications")
    router.my_chat_member.register(member_status, F.chat.type == "private")
    return router
