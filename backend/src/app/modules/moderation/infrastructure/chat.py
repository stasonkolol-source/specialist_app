"""Чат модераторов в Telegram (DEVELOPMENT_PLAN 2.5b, K29): карточка нового кейса уходит ботом
в закрытый чат `TELEGRAM_MODERATORS_CHAT_ID`; текст и кнопки — application/case_card.py. Чат не
задан — карточек нет, кейсы решают командами `cli`.

Кейс о фото — само фото (вариант `md`) с карточкой в подписи. Фото Bot API не принял (формат,
размер) — карточка уходит текстом: модератор получит кейс в любом случае, а фото посмотрит в
админке."""

from typing import Final

import structlog

from app.modules.moderation.application.case_card import card_buttons, card_caption, card_text
from app.modules.moderation.application.dto import CaseContext
from app.modules.moderation.domain.cases import Case
from app.platform.i18n.translator import Translator
from app.platform.kernel.clock import Clock
from app.platform.telegram.port import (
    OutgoingMessage,
    OutgoingPhoto,
    TelegramRejectedError,
    TelegramSender,
)

log = structlog.get_logger(__name__)

PHOTO_EXTENSIONS: Final = {"image/webp": "webp", "image/jpeg": "jpg", "image/png": "png"}


class TelegramModeratorsChat:
    """Порт ModeratorsChat: карточка уходит ботом в чат модераторов."""

    def __init__(
        self,
        sender: TelegramSender,
        translator: Translator,
        chat_id: int | None,
        *,
        clock: Clock,
        admin_url: str | None = None,
    ) -> None:
        self._sender, self._translator, self._chat_id = sender, translator, chat_id
        self._clock, self._admin_url = clock, admin_url

    @property
    def enabled(self) -> bool:
        return self._chat_id is not None

    async def post(self, case: Case, context: CaseContext) -> None:
        if self._chat_id is None:
            return
        now = self._clock.now()
        buttons = card_buttons(case, self._translator, self._admin_url)
        if context.photo is not None:
            extension = PHOTO_EXTENSIONS.get(context.photo.content_type, "webp")
            try:
                await self._sender.send_photo(
                    OutgoingPhoto(
                        chat_id=self._chat_id,
                        photo=context.photo.body,
                        filename=f"case-{case.id}.{extension}",
                        caption=card_caption(
                            case, context, self._translator, now=now, admin_url=self._admin_url
                        ),
                        buttons=buttons,
                    )
                )
            except TelegramRejectedError as exc:
                log.warning(
                    "moderators_chat_photo_rejected", case_id=str(case.id), reason=exc.reason
                )
            else:
                return
        await self._sender.send(
            OutgoingMessage(
                chat_id=self._chat_id,
                text=card_text(case, context, self._translator, now=now, admin_url=self._admin_url),
                buttons=buttons,
            )
        )
