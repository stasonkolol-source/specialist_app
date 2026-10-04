"""«Поделиться» (POST /share; DEVELOPMENT_PLAN 7.4, ARCHITECTURE §11.4).

Что показать в карточке и видна ли сущность всем, решает BFF (interfaces/http/views/share.py):
growth не видит модулей specialists и jobs (DAG §5.4). Здесь — ссылка и карточка для чата:

1. У вошедшего — его код приглашения `_r<code>` (создаётся при первом шаринге) и событие
   ShareCreated (аналитика `share_created`) — в одной транзакции.
2. Карточка `savePreparedInlineMessage` — после commit, вне транзакции: Bot API может
   ответить не сразу. Не принял или вошёл не через Telegram — ссылка без карточки, клиент
   делится ею сам.

Гость получает ссылку без суффикса и без карточки: приписывать некому, а карточку Telegram
готовит только для пользователя бота.
"""

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.growth.api import SharedLink, ShareTarget, ShareText
from app.modules.growth.application.ports import ReferralCodes
from app.modules.growth.domain.share import share_start_param, share_url
from app.modules.identity.api import IdentityApi
from app.platform.contracts.events.growth import ShareCreated
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId
from app.platform.telegram.deeplinks import LinkType
from app.platform.telegram.port import PreparedMessages, ShareCard

LINK_TYPES: Final = {ShareTarget.SPECIALIST: LinkType.SPECIALIST, ShareTarget.JOB: LinkType.JOB}


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateShareCommand:
    sharer_id: UserId | None
    """None — гость."""
    target: ShareTarget
    target_id: UUID
    card: ShareText


@dataclass(frozen=True, slots=True, kw_only=True)
class BotLink:
    """Username бота окружения: из него собирается `https://t.me/<bot>?startapp=`."""

    username: str


class CreateShare:
    def __init__(
        self,
        uow: UnitOfWork,
        codes: ReferralCodes,
        identity: IdentityApi,
        prepared: PreparedMessages,
        clock: Clock,
        bot: BotLink,
    ) -> None:
        self._uow, self._codes, self._identity = uow, codes, identity
        self._prepared, self._clock, self._bot = prepared, clock, bot

    async def __call__(self, cmd: CreateShareCommand) -> SharedLink:
        link_type = LINK_TYPES[cmd.target]
        if cmd.sharer_id is None:
            start_param = share_start_param(link_type, cmd.target_id, ref=None)
            return SharedLink(
                start_param=start_param,
                url=share_url(self._bot.username, start_param),
                prepared_message_id=None,
            )
        async with self._uow:
            ref = await self._codes.code_of(cmd.sharer_id)
        start_param = share_start_param(link_type, cmd.target_id, ref=ref)
        url = share_url(self._bot.username, start_param)
        prepared_id = await self._prepare(cmd.sharer_id, cmd.card, url)
        async with self._uow:
            self._uow.add_event(
                ShareCreated(
                    sharer_id=cmd.sharer_id,
                    entity_type=cmd.target.value,
                    prepared=prepared_id is not None,
                    occurred_at=self._clock.now(),
                )
            )
        return SharedLink(start_param=start_param, url=url, prepared_message_id=prepared_id)

    async def _prepare(self, sharer_id: UserId, text: ShareText, url: str) -> str | None:
        # в личном чате с ботом chat_id равен Telegram id (identity.telegram_chat_id)
        telegram_id = await self._identity.telegram_chat_id(sharer_id)
        if telegram_id is None:
            return None
        card = ShareCard(
            title=text.title,
            description=text.description,
            text=text.text,
            button_text=text.button_text,
            url=url,
        )
        return await self._prepared.prepare(telegram_id, card)
