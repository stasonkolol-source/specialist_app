"""База ORM-моделей (ADR-0020 §5, §10; ARCHITECTURE §7.1).

- Одна схема PostgreSQL на модуль: `class Base(ModelBase): __abstract__ = True;
  metadata = module_metadata("jobs")` в `infrastructure/models.py` модуля.
- Имена ограничений и индексов — по naming convention: репозиторий переводит ошибки
  IntegrityError по имени constraint.
- Связи — только `relation(...)` (lazy="raise"): агрегат загружается целиком явным select.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Integer, MetaData, func, text
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    declared_attr,
    mapped_column,
    relationship,
)

NAMING_CONVENTION: dict[str, str] = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}


def module_metadata(schema: str) -> MetaData:
    """MetaData схемы модуля с общим naming convention."""
    return MetaData(schema=schema, naming_convention=NAMING_CONVENTION)


class ModelBase(DeclarativeBase):
    """Корень ORM-иерархии. Своих таблиц нет: у каждого модуля — свой abstract Base."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012 — атрибут SQLAlchemy
        datetime: DateTime(timezone=True),
    }


def relation(*args: Any, **kwargs: Any) -> Any:
    """relationship с lazy="raise" по умолчанию: ленивой загрузки в async нет."""
    kwargs.setdefault("lazy", "raise")
    return relationship(*args, **kwargs)


class UuidPkMixin:
    """UUIDv7: генерирует приложение (new_id), дефолт в БД — uuidv7() PostgreSQL 18."""

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))


class TimestampsMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class SoftDeleteMixin:
    """deleted_at: удалённое пропадает из выдачи сразу, физически удаляет ретеншн."""

    deleted_at: Mapped[datetime | None] = mapped_column(default=None)


class VersionMixin:
    """Optimistic locking: version_id_col без генератора — новую версию ставит репозиторий."""

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:  # noqa: N805 — declared_attr получает класс
        # __table__ появляется у маппленного класса, в миксине его ещё нет
        table = cls.__table__  # type: ignore[attr-defined]
        return {"version_id_col": table.c.version, "version_id_generator": False}
