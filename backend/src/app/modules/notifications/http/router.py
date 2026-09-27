"""HTTP notifications: каналы доставки (ARCHITECTURE §8.5, §11.1). Центр уведомлений — 2.3b."""

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter

from app.modules.notifications.application.use_cases.grant_telegram_write_access import (
    GrantTelegramWriteAccess,
    GrantTelegramWriteAccessCommand,
)
from app.modules.notifications.domain.channel import GrantedVia
from app.modules.notifications.http.schemas import TelegramChannelOut
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.principal import Principal

router = APIRouter(tags=["notifications"])


@router.post("/me/telegram/write-access", dependencies=AUTHENTICATED)
@inject
async def grant_telegram_write_access(
    principal: FromDishka[Principal], grant: FromDishka[GrantTelegramWriteAccess]
) -> TelegramChannelOut:
    """Пользователь разрешил боту писать: Mini App вызывает после успешного `requestWriteAccess`.

    Повтор идемпотентен: доступный канал не меняется. Нет Telegram-аккаунта — 409
    `telegram_not_linked`.
    """
    channel = await grant(
        GrantTelegramWriteAccessCommand(user_id=principal.user_id, via=GrantedVia.MINI_APP)
    )
    return TelegramChannelOut.of(channel)
