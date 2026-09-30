"""Структурные логи structlog (ARCHITECTURE §13.5, ADR-0020 §10).

JSON в stage и prod, человекочитаемый вывод в dev. Контекст запроса (`request_id`,
`trace_id`, `user_id` — внутренний UUID, `job_id`) кладётся через contextvars.
"""

import logging
import sys
from typing import Any

import structlog

from app.platform.observability.masking import mask_event_dict
from app.platform.settings import AppSettings

CONTEXT_KEYS = ("request_id", "trace_id", "user_id", "job_id")
QUIET_LOGGERS = ("anthropic", "openai", "httpx", "httpx2", "httpcore", "httpcore2")


def configure_logging(app: AppSettings) -> None:
    """Настроить structlog и стандартный logging один раз при старте процесса."""
    level = logging.getLevelNamesMapping().get(app.log_level.upper(), logging.INFO)
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        mask_event_dict,
    ]
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if app.log_json
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )
    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
    # Логи библиотек (uvicorn, sqlalchemy, aiogram) — через тот же формат и маскирование.
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # SDK AI на DEBUG пишут тело запроса — текст пользователя и промпт: не ниже INFO
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(max(level, logging.INFO))


def bind_context(**values: str | None) -> None:
    """Добавить в контекст логов поля запроса или задачи (только из CONTEXT_KEYS)."""
    unknown = set(values) - set(CONTEXT_KEYS)
    if unknown:
        raise ValueError(f"unknown log context keys: {sorted(unknown)}")
    structlog.contextvars.bind_contextvars(**{k: v for k, v in values.items() if v is not None})


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()
