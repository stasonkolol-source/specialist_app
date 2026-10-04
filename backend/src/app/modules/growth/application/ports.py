"""Порты модуля growth (ADR-0020 §3, §5)."""

from datetime import datetime
from typing import Final, Protocol

from app.modules.growth.domain.attribution import FirstTouch
from app.platform.contracts.events.identity import UserDeleted, UserRegistered
from app.platform.kernel.ids import UserId
from app.platform.queue.port import TaskRef


class AttributionRepository(Protocol):
    """Атрибуция — простая запись (ADR-0020 §5): правило одно — первое касание."""

    async def record_first_touch(self, user_id: UserId, touch: FirstTouch, *, at: datetime) -> bool:
        """Записать первое касание; запись уже есть — ничего не меняет.

        True — записано сейчас. UserNotFoundError — пользователя нет. Нужен активный UoW.
        """
        ...

    async def forget(self, user_id: UserId) -> None:
        """Удалить атрибуцию пользователя (аккаунт удалён, §7.10). Нужен активный UoW."""
        ...


class ReferralCodes(Protocol):
    """Код приглашения пользователя (`growth.referral_codes`): один на аккаунт, навсегда."""

    async def code_of(self, owner_id: UserId) -> str:
        """Код владельца; нет — создать. UserNotFoundError — пользователя нет. Активный UoW."""
        ...

    async def forget(self, owner_id: UserId) -> None:
        """Удалить код (аккаунт удалён, §7.10): старые ссылки больше никого не приписывают.
        Активный UoW."""
        ...


RECORD_ATTRIBUTION: Final = TaskRef("growth.record_attribution", UserRegistered)
"""Подписчик UserRegistered: первое касание нового пользователя."""

FORGET_ATTRIBUTION: Final = TaskRef("growth.forget_attribution", UserDeleted)
"""Подписчик UserDeleted: атрибуция удалённого аккаунта (§7.10)."""
