"""Sentry включается, только если задан DSN (DEVELOPMENT_PLAN 0.4, 3.3, K20).

Окружение — APP_ENV, релиз — APP_RELEASE или версия образа Kamal (settings.py); процесс
(web, bot, worker, worker-media, cli) — тег `process`. FastAPI и SQLAlchemy Sentry ловит
сам; ошибки хендлеров бота и фоновых задач отправляют свои прослойки
(interfaces/bot/middlewares.py, platform/queue/tasks.py), а ERROR-логи библиотек
(Procrastinate о проваленной задаче, aiogram о сбое polling) — интеграция logging.
Всё проходит `_scrub`: маскирование ПД и секретов во всём событии.

Значений локальных переменных кадров и тел запросов в событиях нет (8.4): по имени поля их не
замаскировать. В кадрах aiogram — адрес Bot API с токеном бота (`make_request`), методы с текстом
исходящего сообщения (`SendMessage(text=…)`) и секретом webhook (`SetWebhook(secret_token=…)`),
в кадрах входа персонала — секреты учётной записи; тело запроса — сырой апдейт Telegram в режиме
webhook (имя, username, текст сообщения) и свободный текст форм API. SDK их не собирает
(`include_local_variables`, `max_request_body_size`), `_scrub` выбрасывает их ещё раз — на случай
интеграции или кода, который положит их в событие сам.
"""

from collections.abc import Iterator
from typing import Any

import sentry_sdk

from app.platform.observability.masking import mask_value
from app.platform.settings import Settings

FLUSH_SECONDS = 10.0


class SentryTestError(RuntimeError):
    """Тестовая ошибка `cli sentry-test`: проверка, что события доходят до Sentry (3.3)."""


def _frames(event: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Кадры всех стеков события: свой (`attach_stacktrace`), исключений и потоков."""
    stacktraces = [event.get("stacktrace")]
    for key in ("exception", "threads"):
        values = event.get(key)
        if isinstance(values, dict):
            stacktraces += [
                v.get("stacktrace") for v in values.get("values") or () if isinstance(v, dict)
            ]
    for stacktrace in stacktraces:
        if isinstance(stacktrace, dict):
            yield from (f for f in stacktrace.get("frames") or () if isinstance(f, dict))


def _scrub(event: Any, _hint: Any) -> Any:
    """Выбросить переменные кадров и тело запроса, замаскировать ПД и секреты в остальном."""
    if isinstance(event, dict):
        for frame in _frames(event):
            frame.pop("vars", None)
        if isinstance(request := event.get("request"), dict):
            request.pop("data", None)
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
        # переменные кадров и тела запросов — не собирать вовсе (docstring модуля)
        include_local_variables=False,
        max_request_body_size="never",
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
