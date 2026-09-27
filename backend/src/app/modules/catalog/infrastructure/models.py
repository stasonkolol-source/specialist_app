"""ORM-модели catalog (ARCHITECTURE §7.3, §7.5, миграция catalog_0001).

- `categories`: дерево — `parent_id` и денормализованный `path int[]` (предки и сам узел)
  под GIN. `path` и `depth` считает триггер БД при вставке и смене `parent_id`, с каскадом
  на потомков: код их не пишет, и после правки в админке (2.7b) они тоже верны.
- `search_terms`: `norm` — генерируемая колонка `platform.search_norm(term)`, один ключ
  для ru, sr-Latn, sr-Cyrl и en; btree для префикса и GiST trgm для опечаток (§9.1, §9.7).
- `seed_hash` — хэш данных сида: повторный `cli seed` ничего не меняет.
"""

from collections.abc import Mapping
from typing import Any, override

from sqlalchemy import (
    ARRAY,
    REAL,
    Boolean,
    CheckConstraint,
    Computed,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.modules.catalog.api import RiskLevel
from app.modules.catalog.domain.category import MAX_DEPTH, PriceHint, PriceUnit
from app.platform.db.base import ModelBase, module_metadata
from app.platform.db.types import LocalizedTextType, localized_text_check, str_enum
from app.platform.kernel.localized import Locale, LocalizedText
from app.platform.kernel.money import Money

SCHEMA = "catalog"
metadata = module_metadata(SCHEMA)


class Base(ModelBase):
    __abstract__ = True
    metadata = metadata


def price_hints_json(hints: Mapping[str, PriceHint]) -> dict[str, dict[str, Any]]:
    """{"novi-sad": {"min": 100000, "max": 240000, "unit": "hour"}}: суммы в пара (§7.3)."""
    return {
        city: {"min": hint.min.amount, "max": hint.max.amount, "unit": hint.unit.value}
        for city, hint in sorted(hints.items())
    }


class PriceHintsType(TypeDecorator[Mapping[str, PriceHint]]):
    """Ориентиры цены по slug города ↔ JSONB."""

    impl = JSONB
    cache_ok = True

    @override
    def process_bind_param(self, value: Mapping[str, PriceHint] | None, dialect: Dialect) -> Any:
        return None if value is None else price_hints_json(value)

    @override
    def process_result_value(self, value: Any, dialect: Dialect) -> Mapping[str, PriceHint] | None:
        if value is None:
            return None
        return {
            city: PriceHint(
                min=Money(raw["min"]), max=Money(raw["max"]), unit=PriceUnit(raw["unit"])
            )
            for city, raw in value.items()
        }


def _required_locales(column: str) -> CheckConstraint:
    return CheckConstraint(f"{column} ?& ARRAY['ru', 'sr-Cyrl']", name=f"{column}_required_locales")


class CategoryRow(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[LocalizedText] = mapped_column(LocalizedTextType)
    path: Mapped[list[int]] = mapped_column(ARRAY(Integer))
    """Предки и сам узел: {1,12,57}. Пишет триггер catalog.set_category_path."""
    depth: Mapped[int] = mapped_column(SmallInteger)
    """Число элементов path. Пишет тот же триггер."""
    icon: Mapped[str | None] = mapped_column(String(32))
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    jobs_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    max_responses: Mapped[int] = mapped_column(SmallInteger, server_default=text("5"))
    price_hint: Mapped[Mapping[str, PriceHint]] = mapped_column(
        PriceHintsType, server_default=text("'{}'::jsonb")
    )
    risk_level: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    seed_hash: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        localized_text_check("name"),
        _required_locales("name"),
        CheckConstraint(f"depth BETWEEN 1 AND {MAX_DEPTH}", name="depth"),
        CheckConstraint("cardinality(path) = depth AND path[depth] = id", name="path"),
        CheckConstraint("max_responses > 0", name="max_responses"),
        CheckConstraint("jsonb_typeof(price_hint) = 'object'", name="price_hint_object"),
        CheckConstraint(
            f"risk_level BETWEEN {RiskLevel.NORMAL:d} AND {RiskLevel.FORBIDDEN:d}",
            name="risk_level",
        ),
        Index("ix_categories_path", "path", postgresql_using="gin"),
    )


class TagRow(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[LocalizedText] = mapped_column(LocalizedTextType)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    __table_args__ = (
        localized_text_check("name"),
        _required_locales("name"),
        Index("ix_tags_category_id", "category_id"),
    )


class SearchTermRow(Base):
    __tablename__ = "search_terms"

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    term: Mapped[str] = mapped_column(String(120))
    lang: Mapped[Locale] = mapped_column(str_enum(Locale, "lang"))
    norm: Mapped[str] = mapped_column(
        # ::text — как PostgreSQL хранит выражение; иначе alembic check видит расхождение
        Text,
        Computed("platform.search_norm(term::text)", persisted=True),
    )
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    """Категория строки; у тега — категория тега: поиск всегда знает категорию."""
    tag_id: Mapped[int | None] = mapped_column(ForeignKey("tags.id"))
    weight: Mapped[float] = mapped_column(REAL, server_default=text("1.0"))

    __table_args__ = (
        Index(
            "uq_search_terms_category_id_tag_id_lang_term",
            "category_id",
            "tag_id",
            "lang",
            "term",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_search_terms_norm", "norm"),
        Index(
            "ix_search_terms_norm_trgm",
            "norm",
            postgresql_using="gist",
            postgresql_ops={"norm": "gist_trgm_ops"},
        ),
        Index("ix_search_terms_tag_id", "tag_id"),
    )
