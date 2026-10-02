"""MetaData модулей для Alembic (DEVELOPMENT_PLAN 0.9).

Модуль, у которого появились ORM-модели, добавляет сюда свою MetaData в том же шаге:
иначе `alembic check` не увидит его таблицы. Живёт в entrypoints — композиционном
корне, которому разрешено знать infrastructure модулей.
"""

from sqlalchemy import MetaData

from app.modules.catalog.infrastructure.models import metadata as catalog
from app.modules.deals.infrastructure.models import metadata as deals
from app.modules.geo.infrastructure.models import metadata as geo
from app.modules.growth.infrastructure.models import metadata as growth
from app.modules.identity.infrastructure.models import metadata as identity
from app.modules.jobs.infrastructure.models import metadata as jobs
from app.modules.media.infrastructure.models import metadata as media
from app.modules.moderation.infrastructure.models import metadata as moderation
from app.modules.notifications.infrastructure.models import metadata as notifications
from app.modules.pricing.infrastructure.models import metadata as pricing
from app.modules.reviews.infrastructure.models import metadata as reviews
from app.modules.search.infrastructure.models import metadata as search
from app.modules.specialists.infrastructure.models import metadata as specialists
from app.platform.db.platform_tables import metadata as platform


def module_metadatas() -> list[MetaData]:
    return [
        platform,
        identity,
        geo,
        catalog,
        notifications,
        growth,
        media,
        moderation,
        specialists,
        pricing,
        jobs,
        deals,
        reviews,
        search,
    ]
