"""MetaData модулей для Alembic (DEVELOPMENT_PLAN 0.9).

Модуль, у которого появились ORM-модели, добавляет сюда свою MetaData в том же шаге:
иначе `alembic check` не увидит его таблицы. Живёт в entrypoints — композиционном
корне, которому разрешено знать infrastructure модулей.
"""

from sqlalchemy import MetaData

from app.modules.catalog.infrastructure.models import metadata as catalog
from app.modules.geo.infrastructure.models import metadata as geo
from app.modules.growth.infrastructure.models import metadata as growth
from app.modules.identity.infrastructure.models import metadata as identity
from app.modules.media.infrastructure.models import metadata as media
from app.modules.moderation.infrastructure.models import metadata as moderation
from app.modules.notifications.infrastructure.models import metadata as notifications
from app.platform.db.platform_tables import metadata as platform


def module_metadatas() -> list[MetaData]:
    return [platform, identity, geo, catalog, notifications, growth, media, moderation]
