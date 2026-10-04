"""Чат модераторов в Telegram (DEVELOPMENT_PLAN 2.5b, K29): карточка нового кейса уходит ботом
в закрытый чат `TELEGRAM_MODERATORS_CHAT_ID`; текст и кнопки — application/case_card.py. Чат не
задан — карточек нет, кейсы решают командами `cli`."""

from app.modules.moderation.application.case_card import card_buttons, card_text
from app.modules.moderation.domain.cases import Case
from app.platform.i18n.translator import Translator
from app.platform.telegram.port import OutgoingMessage, TelegramSender


class TelegramModeratorsChat:
    """Порт ModeratorsChat: карточка уходит ботом в чат модераторов."""

    def __init__(self, sender: TelegramSender, translator: Translator, chat_id: int | None) -> None:
        self._sender, self._translator, self._chat_id = sender, translator, chat_id

    @property
    def enabled(self) -> bool:
        return self._chat_id is not None

    async def post(self, case: Case) -> None:
        if self._chat_id is None:
            return
        await self._sender.send(
            OutgoingMessage(
                chat_id=self._chat_id,
                text=card_text(case, self._translator),
                buttons=card_buttons(case, self._translator),
            )
        )
