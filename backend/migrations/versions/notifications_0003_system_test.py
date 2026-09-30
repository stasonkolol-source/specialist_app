"""notifications_0003: тип `system.test` — проверка канала (`cli notify-test`, DEVELOPMENT_PLAN 2.3b).

Новый CHECK — надмножество старого, длина varchar (30) не меняется. DROP → ADD … NOT VALID
→ VALIDATE после commit, как в media_0003; повторный upgrade после сбоя проходит.
Downgrade удаляет строки `system.test`: со старым CHECK они бы не прошли VALIDATE.

Ревизия: notifications_0003 (2026-09-30 12:00:00.000000+00:00)
Предыдущая: notifications_0002

Правила (DEVELOPMENT_PLAN 0.9, ADR-0005):
- имя ревизии — <модуль>_NNNN, файл — <модуль>_NNNN_<slug>.py;
- миграции идут под ролью migrator: lock_timeout = 3s задан роли, долгих блокировок нет;
- индексы на живых таблицах — CREATE INDEX CONCURRENTLY внутри op.get_context().autocommit_block();
- expand/contract: сначала добавить (nullable, новая колонка, двойная запись), удалять — отдельной
  миграцией после выкладки кода, который старое больше не читает.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "notifications_0003"
down_revision: str | Sequence[str] | None = "notifications_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "notifications.notifications"
CHECK = "ck_notifications_type"
OLD = (
    "'job.matched', 'response.received', 'response.accepted', 'response.not_selected',"
    " 'job.invited', 'message.received', 'deal.proposed', 'deal.cancelled', 'dispute.opened',"
    " 'deal.reminder', 'deal.completion_prompt', 'review.request', 'review.published',"
    " 'moderation.decision', 'job.expiring', 'job.expired', 'profile.stale_reminder',"
    " 'account.restricted'"
)
NEW = f"{OLD}, 'system.test'"


def _types(values: str) -> None:
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CHECK}")
    op.execute(f"ALTER TABLE {TABLE} ADD CONSTRAINT {CHECK} CHECK (type IN ({values})) NOT VALID")
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CHECK}")


def upgrade() -> None:
    _types(NEW)


def downgrade() -> None:
    op.execute(
        "DELETE FROM notifications.deliveries WHERE notification_id IN"
        " (SELECT id FROM notifications.notifications WHERE type = 'system.test')"
    )
    op.execute("DELETE FROM notifications.notifications WHERE type = 'system.test'")
    _types(OLD)
