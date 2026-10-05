"""notifications_0009: тип `deal.agreed` — «Договорились» предложившей стороне (UX_GUIDANCE №14).

Вторая сторона подтвердила условия «Договориться» из чата (S53): предложившему — «Условия
подтверждены» и «Открыть чат»; раньше он видел это только строкой в чате. Новый CHECK —
надмножество старого, длина varchar (30) не меняется. DROP → ADD … NOT VALID → VALIDATE после
commit, как в notifications_0005. Downgrade удаляет строки нового типа.

Ревизия: notifications_0009 (2026-10-05 21:30:00.000000+00:00)
Предыдущая: messaging_0003

Правила (DEVELOPMENT_PLAN 0.9, ADR-0005):
- имя ревизии — <модуль>_NNNN, файл — <модуль>_NNNN_<slug>.py;
- миграции идут под ролью migrator: lock_timeout = 3s задан роли, долгих блокировок нет;
- индексы на живых таблицах — CREATE INDEX CONCURRENTLY внутри op.get_context().autocommit_block();
- expand/contract: сначала добавить (nullable, новая колонка, двойная запись), удалять — отдельной
  миграцией после выкладки кода, который старое больше не читает.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "notifications_0009"
down_revision: str | Sequence[str] | None = "messaging_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "notifications.notifications"
CHECK = "ck_notifications_type"
OLD = (
    "'job.matched', 'job.digest', 'response.received', 'response.accepted',"
    " 'response.not_selected', 'job.invited', 'message.received', 'deal.proposed',"
    " 'deal.cancelled', 'dispute.opened', 'dispute.resolved', 'deal.reminder',"
    " 'deal.completion_prompt', 'review.request', 'review.published', 'moderation.decision',"
    " 'job.expiring', 'job.expired', 'profile.stale_reminder', 'profile.published',"
    " 'account.restricted', 'system.test', 'broadcast'"
)
NEW = f"{OLD}, 'deal.agreed'"


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
        " (SELECT id FROM notifications.notifications WHERE type = 'deal.agreed')"
    )
    op.execute("DELETE FROM notifications.notifications WHERE type = 'deal.agreed'")
    _types(OLD)
