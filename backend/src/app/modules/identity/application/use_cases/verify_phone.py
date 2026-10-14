"""«Подтвердить телефон» (POST /me/phone; S33, S32c, S43; ADR-0009, ADR-0016 §2): добровольный
бейдж «Телефон подтверждён» одним нажатием. Mini App отдаёт подписанный ответ `requestContact`;
номер принимается, только если подпись бота верна и свежа, а контакт — Telegram-аккаунта этого
пользователя. Один номер — один аккаунт: занятый — 409 `phone_taken`. Уровень доверия
пересчитывается в той же транзакции (телефон → 1). Номер наружу не уходит: ни в ответ, ни в
логи, ни в событие."""

from dataclasses import dataclass

from app.modules.identity.application.ports import PhoneContacts, UserRepository
from app.modules.identity.application.trust import TrustRecalculation
from app.modules.identity.domain.user import AuthProvider
from app.modules.identity.errors import InvalidPhoneContactError, PhoneTakenError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class VerifyPhoneCommand:
    actor_id: UserId
    contact: str
    """Подписанный ответ `requestContact` Mini App (`contact=…&auth_date=…&hash=…`)."""


class VerifyPhone:
    def __init__(
        self,
        uow: UnitOfWork,
        users: UserRepository,
        contacts: PhoneContacts,
        trust: TrustRecalculation,
        clock: Clock,
    ) -> None:
        self._uow, self._users, self._contacts = uow, users, contacts
        self._trust, self._clock = trust, clock

    async def __call__(self, cmd: VerifyPhoneCommand) -> bool:
        """True — номер подтверждён сейчас; False — этот же номер уже был подтверждён."""
        shared = self._contacts.verify(cmd.contact)
        async with self._uow:
            user = await self._users.get_for_update(cmd.actor_id)
            own = {i.subject for i in user.identities if i.provider is AuthProvider.TELEGRAM}
            if str(shared.telegram_id) not in own:
                raise InvalidPhoneContactError(reason="not_own")
            # проверка до записи: нарушение уникального индекса попало бы номером в журнал БД
            if await self._users.phone_taken(shared.phone_e164, by_other_than=user.id):
                raise PhoneTakenError
            now = self._clock.now()
            if not user.verify_phone(phone_e164=shared.phone_e164, now=now):
                return False
            await self._trust.apply(user, now=now)
            await self._users.save(user)
        return True
