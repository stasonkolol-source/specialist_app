"""growth_0004: коды приглашения `referral_codes` (ARCHITECTURE §7.3, §11.4; DEVELOPMENT_PLAN 7.4).

Ссылка «Поделиться» вошедшего несёт его код `_r<code>`: новый пользователь по ней получает этот
код в первом касании (`attributions.referral_code`) — так считается K-фактор шаринга. Код один
на аккаунт (`owner_id` UNIQUE), создаётся при первом шаринге; удаление аккаунта стирает его.
FK на identity.users — только здесь, в моделях его нет (migrations/env.py). Таблица новая и
пустая: индексы — обычные.

Ревизия: growth_0004 (2026-10-04 10:00:00.000000+00:00)
Предыдущая: moderation_0005

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

revision: str = "growth_0004"
down_revision: str | Sequence[str] | None = "specialists_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "growth"


def upgrade() -> None:
    op.create_table(
        "referral_codes",
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["identity.users.id"], name=op.f("fk_referral_codes_owner_id_users")
        ),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_referral_codes")),
        sa.UniqueConstraint("owner_id", name=op.f("uq_referral_codes_owner_id")),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("referral_codes", schema=SCHEMA)
