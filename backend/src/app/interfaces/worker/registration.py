"""Регистрация задач воркера (DEVELOPMENT_PLAN 0.12).

Импорт tasks.py модулей заполняет декларативный реестр TASKS; здесь он переносится в
приложение Procrastinate. Подписки на события для всех процессов собирает
entrypoints/_wiring.build_event_registry — тоже из tasks.py модулей.
"""

import procrastinate

import app.platform.queue.periodic  # noqa: F401 — регистрирует периодические задачи платформы
from app.platform.queue.tasks import TASKS, TaskRegistry, register_tasks


def register_worker_tasks(app: procrastinate.App, registry: TaskRegistry = TASKS) -> None:
    register_tasks(app, registry)
