"""Entitlements MVP (ADR-0018): тарифов нет — квот нет, все фичи доступны."""

from app.platform.entitlements.port import Entitlements
from app.platform.kernel.ids import UserId


class UnlimitedEntitlements(Entitlements):
    async def quota(self, user_id: UserId, feature: str) -> int | None:  # noqa: ARG002 — квот нет
        return None

    async def has(self, user_id: UserId, feature: str) -> bool:  # noqa: ARG002 — всё доступно
        return True
