"""Отправитель Telegram для тестов (ADR-0020 §11): запоминает сообщения, может падать."""

from dataclasses import dataclass, field

from app.platform.kernel.errors import ExternalServiceError
from app.platform.telegram.port import OutgoingMessage, SentMessage


@dataclass
class RecordingTelegramSender:
    sent: list[OutgoingMessage] = field(default_factory=list)
    failing: bool = False
    """Bot API недоступен: send бросает ExternalServiceError."""

    async def send(self, message: OutgoingMessage) -> SentMessage:
        if self.failing:
            raise ExternalServiceError(service="telegram")
        self.sent.append(message)
        return SentMessage(message_id=1000 + len(self.sent))
