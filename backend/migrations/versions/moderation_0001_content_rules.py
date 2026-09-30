"""moderation_0001: словарь контент-правил (ARCHITECTURE §7.3, §14.1, DEVELOPMENT_PLAN 2.4).

`content_rules` — стоп-слова, регулярки по скелету текста и домены (modules/moderation/
domain/rules.py). Правило определяет пара (kind, pattern). `origin` — откуда строка: сид
(`cli seed` из seeds/moderation/content_rules.yaml) или админка (2.7b); строки админки сид не
трогает. Регулярки — только из сида (`ck_content_rules_regex_from_seed`): стандартный `re`
перебирает варианты экспоненциально на неудачной регулярке, а сид проходит ревью и
seeds-validate; регулярки из админки — после движка с линейным временем (RE2). Схема moderation создана в platform_0001. Таблица новая и пустая: словарь загружает
`cli seed` после миграции.

Ревизия: moderation_0001 (2026-09-30 18:00:00.000000+00:00)
Предыдущая: notifications_0003

Правила (DEVELOPMENT_PLAN 0.9, ADR-0005):
- имя ревизии — <модуль>_NNNN, файл — <модуль>_NNNN_<slug>.py;
- миграции идут под ролью migrator: lock_timeout = 3s задан роли, долгих блокировок нет;
- индексы на живых таблицах — CREATE INDEX CONCURRENTLY внутри op.get_context().autocommit_block();
- expand/contract: сначала добавить (nullable, новая колонка, двойная запись), удалять — отдельной
  миграцией после выкладки кода, который старое больше не читает.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "moderation_0001"
down_revision: str | Sequence[str] | None = "notifications_0003"
branch_labels: str | Sequence[str] | None = ("moderation",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "content_rules",
        sa.Column("id", sa.Integer(), sa.Identity(always=True), nullable=False),
        sa.Column("pattern", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=14), nullable=False),
        sa.Column("lang", sa.String(length=10), nullable=True),
        sa.Column("action", sa.String(length=14), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("origin", sa.String(length=13), server_default="admin", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('word', 'regex', 'domain')", name=op.f("ck_content_rules_kind")),
        sa.CheckConstraint("lang IN ('ru', 'sr', 'uk', 'en')", name=op.f("ck_content_rules_lang")),
        sa.CheckConstraint("action IN ('flag', 'shadow', 'block')", name=op.f("ck_content_rules_action")),
        sa.CheckConstraint(
            "category IN ('drugs', 'weapons', 'escort', 'scam', 'mule', 'contacts', 'spam', 'vacancy')",
            name=op.f("ck_content_rules_category"),
        ),
        sa.CheckConstraint("origin IN ('seed', 'admin')", name=op.f("ck_content_rules_origin")),
        sa.CheckConstraint(
            "kind <> 'regex' OR origin = 'seed'", name=op.f("ck_content_rules_regex_from_seed")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_content_rules")),
        sa.UniqueConstraint("kind", "pattern", name=op.f("uq_content_rules_kind_pattern")),
        schema="moderation",
    )


def downgrade() -> None:
    op.drop_table("content_rules", schema="moderation")
