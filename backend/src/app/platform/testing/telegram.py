"""Отправитель Telegram для тестов (ADR-0020 §11): запоминает сообщения и правки кнопок, может
падать."""

from dataclasses import dataclass, field

from app.platform.kernel.errors import ExternalServiceError
from app.platform.telegram.port import ButtonLine, OutgoingMessage, SentMessage


@dataclass(frozen=True, slots=True, kw_only=True)
class EditedButtons:
    chat_id: int
    message_id: int
    buttons: tuple[ButtonLine, ...]


@dataclass
class RecordingTelegramSender:
    sent: list[OutgoingMessage] = field(default_factory=list)
    edited: list[EditedButtons] = field(default_factory=list)
    failing: bool = False
    """Bot API недоступен: send бросает ExternalServiceError."""
    error: Exception | None = None
    """Ответ Bot API ошибкой порта: 429, 403, 400 (port.py)."""

    async def send(self, message: OutgoingMessage) -> SentMessage:
        if self.error is not None:
            raise self.error
        if self.failing:
            raise ExternalServiceError(service="telegram")
        self.sent.append(message)
        return SentMessage(message_id=1000 + len(self.sent))

    async def edit_buttons(
        self, chat_id: int, message_id: int, buttons: tuple[ButtonLine, ...]
    ) -> None:
        if self.error is not None:
            raise self.error
        if self.failing:
            raise ExternalServiceError(service="telegram")
        self.edited.append(EditedButtons(chat_id=chat_id, message_id=message_id, buttons=buttons))
