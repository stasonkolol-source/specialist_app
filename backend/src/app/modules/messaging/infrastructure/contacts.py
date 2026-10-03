"""Контакт из подписи Telegram (S54, DEVELOPMENT_PLAN 6.3b; ADR-0009): username — из initData
Mini App, телефон — из ответа `requestContact`. Подпись проверяет InitDataVerifier бота; ошибки
входа (401) здесь становятся ошибкой контакта (422): сессия пользователя тут ни при чём."""

from datetime import timedelta
from typing import Final

from app.modules.messaging.application.ports import VerifiedContact
from app.modules.messaging.errors import InvalidContactError
from app.platform.security.errors import InitDataExpiredError, InvalidInitDataError
from app.platform.security.initdata import InitDataVerifier

USERNAME_MAX_AGE: Final = timedelta(days=1)
"""initData для username — не старше суток: Mini App могли открыть давно, а подпись та же."""


class TelegramContactVerifier:
    def __init__(self, verifier: InitDataVerifier) -> None:
        self._verifier = verifier

    def telegram(self, init_data: str) -> VerifiedContact:
        try:
            user = self._verifier.verify(init_data, max_age=USERNAME_MAX_AGE).user
        except InitDataExpiredError:
            raise InvalidContactError(reason="expired") from None
        except InvalidInitDataError:
            raise InvalidContactError(reason="signature") from None
        return VerifiedContact(
            telegram_id=user.id, value=f"@{user.username}" if user.username else None
        )

    def phone(self, contact: str) -> VerifiedContact:
        try:
            shared = self._verifier.verify_contact(contact)
        except InitDataExpiredError:
            raise InvalidContactError(reason="expired") from None
        except InvalidInitDataError:
            raise InvalidContactError(reason="signature") from None
        return VerifiedContact(telegram_id=shared.user_id, value=shared.phone_e164)
