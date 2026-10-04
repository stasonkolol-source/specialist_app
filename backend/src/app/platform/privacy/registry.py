"""Реестр сроков хранения и разделов выгрузки (DEVELOPMENT_PLAN 2.12b, ARCHITECTURE §7.10).

Модуль объявляет своё в `modules/<m>/privacy.py` — как задачи в tasks.py, декларативно:

    @retention_rule("jobs.closed_jobs", keep="24 мес. после закрытия")
    async def closed_jobs(run: RetentionRun) -> int:
        ...  # свой use case из run.container, сколько удалено

    export_section("jobs", ExportTable(JobRow, lambda user: JobRow.client_id == user))

Ночная `platform.retention_sweep` проходит правила, `cli export-user-data` — разделы. Платформа
о модулях не знает: реестр заполняет импорт privacy.py (entrypoints/_wiring.load_module_tasks).
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from dishka import AsyncContainer
from sqlalchemy import ColumnElement, Table


def table_of(model: type[Any]) -> Table:
    """Таблица ORM-класса."""
    table = model.__table__
    if not isinstance(table, Table):
        raise TypeError(f"{model.__name__} is not mapped to a table")
    return table


@dataclass(frozen=True, slots=True)
class RetentionRun:
    """Контекст правила: контейнер процесса и «сейчас» прохода (тест сдвигает часы через него)."""

    container: AsyncContainer
    now: datetime


RetentionHandler = Callable[[RetentionRun], Awaitable[int]]


@dataclass(frozen=True, slots=True)
class RetentionRule:
    name: str
    """`<модуль>.<что>`: имя в логах и отчёте прохода."""
    keep: str
    """Срок по матрице §7.10 — человеку: логи, runbook."""
    handler: RetentionHandler


@dataclass(frozen=True, slots=True)
class ExportTable:
    """Строки таблицы модели, которые принадлежат пользователю: `owner(user_id)` — условие WHERE."""

    model: type[Any]
    """ORM-класс модуля (`…Row`)."""
    owner: Callable[[UUID], ColumnElement[bool]]
    exclude: frozenset[str] = frozenset()
    """Колонки, которые не выгружаем: секреты (хэши токенов) и служебное (tsvector)."""


ExportSupplement = Callable[[AsyncContainer, UUID], Awaitable[Mapping[str, Any]]]
"""Дополнение раздела, которого нет в строках его таблиц: ссылки на файлы, строки по id из
фасада модуля ниже по DAG."""


@dataclass(frozen=True, slots=True)
class ExportSection:
    name: str
    tables: Sequence[ExportTable]
    supplement: ExportSupplement | None = None


@dataclass
class PrivacyRegistry:
    rules: dict[str, RetentionRule] = field(default_factory=dict)
    sections: dict[str, ExportSection] = field(default_factory=dict)

    def add_rule(self, rule: RetentionRule) -> None:
        if rule.name in self.rules:
            raise ValueError(f"retention rule {rule.name} is declared twice")
        self.rules[rule.name] = rule

    def add_section(self, section: ExportSection) -> None:
        if section.name in self.sections:
            raise ValueError(f"export section {section.name} is declared twice")
        self.sections[section.name] = section


PRIVACY = PrivacyRegistry()


def retention_rule(
    name: str, *, keep: str, registry: PrivacyRegistry = PRIVACY
) -> Callable[[RetentionHandler], RetentionHandler]:
    """Объявить правило хранения модуля. Обработчик возвращает, сколько удалено."""

    def decorator(handler: RetentionHandler) -> RetentionHandler:
        registry.add_rule(RetentionRule(name=name, keep=keep, handler=handler))
        return handler

    return decorator


def export_section(
    name: str,
    *tables: ExportTable,
    supplement: ExportSupplement | None = None,
    registry: PrivacyRegistry = PRIVACY,
) -> None:
    """Объявить раздел выгрузки модуля: его таблицы с ПД пользователя и дополнение."""
    registry.add_section(ExportSection(name=name, tables=tables, supplement=supplement))
