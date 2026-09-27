"""Параметры модуля identity (ADR-0020 §3): собирает di.py из настроек."""

from dataclasses import dataclass
from datetime import timedelta

from app.platform.kernel.principal import Platform


@dataclass(frozen=True, slots=True, kw_only=True)
class IdentityConfig:
    bot_id: int | None
    """Бот окружения, чей initData принимаем: пишется в сессию (ADR-0009 п. 7)."""
    refresh_ttl_tma: timedelta
    refresh_ttl_mobile: timedelta

    def refresh_ttl(self, platform: Platform) -> timedelta:
        return self.refresh_ttl_tma if platform is Platform.TMA else self.refresh_ttl_mobile
