"""Sentry включается, только если задан DSN (DEVELOPMENT_PLAN 0.4, 3.3, K20).

Окружение — APP_ENV, релиз — APP_RELEASE или версия образа Kamal (settings.py); процесс
(web, bot, worker, worker-media, cli) — тег `process`. FastAPI и SQLAlchemy Sentry ловит
сам; ошибки хендлеров бота и фоновых задач отправляют свои прослойки
(interfaces/bot/middlewares.py, platform/queue/tasks.py), а ERROR-логи библиотек
(Procrastinate о проваленной задаче, aiogram о сбое polling) — интеграция logging.
Всё проходит `_scrub`: маскирование ПД и секретов во всём событии.
"""

from typing import Any

import sentry_sdk

from app.platform.observability.masking import mask_value
from app.platform.settings import Settings

FLUSH_SECONDS = 10.0


class SentryTestError(RuntimeError):
    """Тестовая ошибка `cli sentry-test`: проверка, что события доходят до Sentry (3.3)."""


def _scrub(event: Any, _hint: Any) -> Any:
    """Маскировать ПД и секреты во всём событии перед отправкой."""
    return mask_value(None, event)


def init_sentry(settings: Settings, *, process: str) -> bool:
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
        before_send_transaction=_scrub,
    )
    # глобальная область: тег получают события всех запросов, задач и апдейтов процесса
    sentry_sdk.get_global_scope().set_tag("process", process)
    return True


def send_test_event() -> str | None:
    """Отправить тестовую ошибку и дождаться отправки. Id события — его ищут в Sentry."""
    try:
        raise SentryTestError("sentry-test: проверка доставки событий (DEVELOPMENT_PLAN 3.3)")
    except SentryTestError:
        event_id = sentry_sdk.capture_exception()
    sentry_sdk.flush(timeout=FLUSH_SECONDS)
    return event_id
