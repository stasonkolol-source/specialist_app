"""ORM-модели moderation (ARCHITECTURE §7.3, миграция moderation_0001).

Кейсы, санкции и сигналы риска — шаг 2.5a; здесь пока словарь контент-правил.
"""

from enum import StrEnum

from sqlalchemy import Boolean, Identity, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.moderation.domain.rules import (
    MAX_PATTERN,
    RuleAction,
    RuleCategory,
    RuleKind,
    RuleLanguage,
)
from app.platform.db.base import ModelBase, TimestampsMixin, module_metadata
from app.platform.db.types import str_enum

SCHEMA = "moderation"
metadata = module_metadata(SCHEMA)


class Base(ModelBase):
    __abstract__ = True
    metadata = metadata


class RuleOrigin(StrEnum):
    SEED = "seed"
    """Из seeds/moderation/content_rules.yaml: `cli seed` создаёт, меняет и выключает."""
    ADMIN = "admin"
    """Завела админка (2.7b): сид такие строки не трогает."""


class ContentRuleRow(TimestampsMixin, Base):
    """Стоп-слово, регулярка по скелету или домен (domain/rules.py)."""

    __tablename__ = "content_rules"

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    pattern: Mapped[str] = mapped_column(String(MAX_PATTERN))
    kind: Mapped[RuleKind] = mapped_column(str_enum(RuleKind, "kind"))
    lang: Mapped[RuleLanguage | None] = mapped_column(str_enum(RuleLanguage, "lang"))
    action: Mapped[RuleAction] = mapped_column(str_enum(RuleAction, "action"))
    category: Mapped[RuleCategory] = mapped_column(str_enum(RuleCategory, "category"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    origin: Mapped[RuleOrigin] = mapped_column(
        str_enum(RuleOrigin, "origin"), server_default=RuleOrigin.ADMIN.value
    )

    __table_args__ = (UniqueConstraint("kind", "pattern"),)
