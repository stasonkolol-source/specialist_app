"""platform_0008: публичный флаг подтверждения телефона (выключен).

Флаг `identity.phone_verification`: включённый — Mini App показывает «Подтвердить телефон»
(S33, S32c, S43), а POST /me/phone принимает контакт; выключенный — строк нет, POST /me/phone
отвечает 404 `phone_verification_unavailable`. Действующая редакция «1» политики
конфиденциальности не описывает цель «бейдж и один номер — один аккаунт»: флаг включают в
админке вместе с вводом редакции 2, без деплоя. Флаг, уже созданный в админке, не
перезаписывается; откат удаляет только выключенный.

Ревизия: platform_0008 (2026-10-14 12:00:00.000000+00:00)
Предыдущая: notifications_0012

Правила (DEVELOPMENT_PLAN 0.9, ADR-0005):
- имя ревизии — <модуль>_NNNN, файл — <модуль>_NNNN_<slug>.py;
- миграции идут под ролью migrator: lock_timeout = 3s задан роли, долгих блокировок нет;
- индексы на живых таблицах — CREATE INDEX CONCURRENTLY внутри op.get_context().autocommit_block();
- expand/contract: сначала добавить (nullable, новая колонка, двойная запись), удалять — отдельной
  миграцией после выкладки кода, который старое больше не читает.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "platform_0008"
down_revision: str | Sequence[str] | None = "notifications_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PHONE_VERIFICATION = "identity.phone_verification"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO platform.feature_flags (key, enabled, public, description)
        VALUES ('{PHONE_VERIFICATION}', false, true,
                'Подтверждение телефона (бейдж): включить вместе с редакцией 2 политики')
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        f"DELETE FROM platform.feature_flags WHERE key = '{PHONE_VERIFICATION}' AND NOT enabled"
    )
