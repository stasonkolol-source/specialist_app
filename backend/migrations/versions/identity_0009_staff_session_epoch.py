"""identity_0009: поколение сессий админки во входе сотрудника (2.7b, ревью безопасности; V7).

Cookie персонала `sosed_admin` подписана, но на сервере не хранится: новые пароль и TOTP
(`cli staff-create`) прежние сессии не закрывали. `identity.staff_credentials.session_epoch`
кладётся в cookie при входе и сверяется на каждом запросе; `staff-create` и `cli staff-revoke` его
увеличивают. Колонка NOT NULL с постоянным умолчанием — PostgreSQL меняет только каталог, таблицу
не переписывает. Cookie, выданные до миграции, поколения не несут: сотрудники входят заново.

Ревизия: identity_0009 (2026-10-04 20:00:00.000000+00:00)
Предыдущая: identity_0008

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

revision: str = "identity_0009"
down_revision: str | Sequence[str] | None = "identity_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "identity"


def upgrade() -> None:
    op.add_column(
        "staff_credentials",
        sa.Column("session_epoch", sa.Integer(), server_default=sa.text("0"), nullable=False),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("staff_credentials", "session_epoch", schema=SCHEMA)
