"""MetaData модулей для Alembic (DEVELOPMENT_PLAN 0.9).

Модуль, у которого появились ORM-модели, добавляет сюда свою MetaData в том же шаге:
иначе `alembic check` не увидит его таблицы. Живёт в entrypoints — композиционном
корне, которому разрешено знать infrastructure модулей.
"""

from sqlalchemy import MetaData

from app.modules.identity.infrastructure.models import metadata as identity


def module_metadatas() -> list[MetaData]:
    return [identity]
