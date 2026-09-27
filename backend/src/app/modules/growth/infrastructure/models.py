"""ORM-модели growth (ARCHITECTURE §7.3, миграция growth_0001).

FK `attributions.user_id` → identity.users объявлен только в миграции: MetaData модуля не
знает чужих таблиц (modules/README.md, migrations/env.py).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.growth.domain.attribution import AttributionSource
from app.platform.contracts.events.identity import EntryPoint
from app.platform.db.base import ModelBase, module_metadata
from app.platform.db.types import str_enum

SCHEMA = "growth"
metadata = module_metadata(SCHEMA)


class Base(ModelBase):
    __abstract__ = True
    metadata = metadata


class AttributionRow(Base):
    """Первое касание: одна строка на пользователя, не перезаписывается."""

    __tablename__ = "attributions"

    user_id: Mapped[UUID] = mapped_column(primary_key=True)
    """identity.users: FK fk_attributions_user_id_users — в миграции growth_0001."""
    source: Mapped[AttributionSource] = mapped_column(str_enum(AttributionSource, "source"))
    start_param: Mapped[str | None] = mapped_column(String(64))
    referral_code: Mapped[str | None] = mapped_column(String(64))
    entry_point: Mapped[EntryPoint | None] = mapped_column(str_enum(EntryPoint, "entry_point"))
    first_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())
