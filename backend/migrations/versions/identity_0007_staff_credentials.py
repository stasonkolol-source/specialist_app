"""identity_0007: вход персонала в админку (DEVELOPMENT_PLAN 2.7a; ADR-0009, ARCHITECTURE §13.2).

`identity.staff_credentials` — логин, хэш пароля (argon2) и секрет TOTP сотрудника; роли — в
`identity.user_roles` (`cli staff-grant`), запись создаёт `cli staff-create`. Логин — латиница в
нижнем регистре, уникален без учёта регистра. `totp_last_step` — шаг последнего принятого кода:
повтор того же кода не входит. Таблица новая и пустая.

Ревизия: identity_0007 (2026-10-04 10:00:00.000000+00:00)
Предыдущая: platform_0005

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

revision: str = "identity_0007"
down_revision: str | Sequence[str] | None = "platform_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "identity"


def upgrade() -> None:
    op.create_table(
        "staff_credentials",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("login", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("totp_secret", sa.String(length=64), nullable=False),
        sa.Column("totp_last_step", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "login ~ '^[a-z0-9._-]{3,64}$'", name=op.f("ck_staff_credentials_login_format")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["identity.users.id"], name=op.f("fk_staff_credentials_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_staff_credentials")),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_staff_credentials_login",
        "staff_credentials",
        [sa.text("lower(login)")],
        unique=True,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("uq_staff_credentials_login", table_name="staff_credentials", schema=SCHEMA)
    op.drop_table("staff_credentials", schema=SCHEMA)
