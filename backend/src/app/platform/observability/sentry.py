"""Sentry включается, только если задан DSN (DEVELOPMENT_PLAN 0.4, K20)."""

from typing import Any

import sentry_sdk

from app.platform.observability.masking import mask_value
from app.platform.settings import Settings


def _scrub(event: Any, _hint: Any) -> Any:
    """Маскировать ПД и секреты во всём событии перед отправкой."""
    return mask_value(None, event)


def init_sentry(settings: Settings) -> bool:
    """Инициализировать Sentry. Возвращает True, если он включён."""
    if settings.sentry.dsn is None:
        return False
    sentry_sdk.init(
        dsn=settings.sentry.dsn.get_secret_value(),
        environment=settings.app.env.value,
        release=settings.app.release,
        traces_sample_rate=settings.sentry.traces_sample_rate,
        send_default_pii=False,
        before_send=_scrub,
    )
    return True
