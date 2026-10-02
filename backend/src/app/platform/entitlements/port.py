"""Порт «что пользователю можно» (ARCHITECTURE §15.2; ADR-0018): продуктовые квоты и фичи.

Проверки в модулях идут по фичам, а не по тарифам: `quota(user, ACTIVE_RESPONSES)`,
`has(user, PRO_BADGE)`. В MVP тарифов и модуля billing нет — заглушка отвечает «без
ограничений» (`unlimited.py`); в v1 её заменит сервис entitlements без переделки модулей.
Антиспам-лимиты (§13.3) — не сюда: они не зависят от тарифа.
"""

from typing import Final, Protocol

from app.platform.kernel.ids import UserId

ACTIVE_RESPONSES: Final = "active_responses"
"""Сколько откликов одновременно ждут решения клиента (v1: бесплатно 10, с Pro 30)."""


class Entitlements(Protocol):
    async def quota(self, user_id: UserId, feature: str) -> int | None:
        """Размер квоты фичи; None — без ограничений."""
        ...

    async def has(self, user_id: UserId, feature: str) -> bool:
        """Доступна ли фича пользователю."""
        ...
