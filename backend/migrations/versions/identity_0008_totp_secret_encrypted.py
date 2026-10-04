"""identity_0008: секрет TOTP персонала — зашифрованным (шаг 8.4; ASVS V6).

`identity.staff_credentials.totp_secret` хранит `v1:<kid>:<base64url>` (AES-256-GCM под
APP_TOTP_KEY, ~92 знака) — колонка расширяется с varchar(64) до varchar(255): PostgreSQL меняет
только каталог, таблицу не переписывает. Данные миграция не трогает — ключа у неё нет: строки до
8.4 (открытый base32) перешифровывают удачный вход сотрудника и `cli staff-totp-reencrypt`.
Откат вернёт varchar(64) и не пройдёт, пока в таблице есть зашифрованные секреты (ADR-0005: данные
не теряем) — старый код их всё равно не прочтёт: сначала `cli staff-create` заново.

Ревизия: identity_0008 (2026-10-04 18:00:00.000000+00:00)
Предыдущая: moderation_0008

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

revision: str = "identity_0008"
down_revision: str | Sequence[str] | None = "moderation_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "identity"


def upgrade() -> None:
    op.alter_column(
        "staff_credentials",
        "totp_secret",
        existing_type=sa.String(length=64),
        type_=sa.String(length=255),
        existing_nullable=False,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.alter_column(
        "staff_credentials",
        "totp_secret",
        existing_type=sa.String(length=255),
        type_=sa.String(length=64),
        existing_nullable=False,
        schema=SCHEMA,
    )
