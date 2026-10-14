"""Телефон из подписи Telegram (POST /me/phone; ADR-0009): ответ `requestContact` Mini App
подписан ботом так же, как initData. Подпись проверяет InitDataVerifier бота; его ошибки входа
(401) здесь становятся ошибкой контакта (422): сессия пользователя тут ни при чём."""

from app.modules.identity.application.dto import SharedPhone
from app.modules.identity.errors import InvalidPhoneContactError
from app.platform.security.errors import InitDataExpiredError, InvalidInitDataError
from app.platform.security.initdata import InitDataVerifier


class TelegramPhoneContacts:
    def __init__(self, verifier: InitDataVerifier) -> None:
        self._verifier = verifier

    def verify(self, contact: str) -> SharedPhone:
        try:
            shared = self._verifier.verify_contact(contact)
        except InitDataExpiredError:
            raise InvalidPhoneContactError(reason="expired") from None
        except InvalidInitDataError:
            raise InvalidPhoneContactError(reason="signature") from None
        return SharedPhone(telegram_id=shared.user_id, phone_e164=shared.phone_e164)
