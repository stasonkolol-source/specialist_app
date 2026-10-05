"""notifications_0009: типы `job.published`, `response.declined`, `deal.completed` (UX-аудит №11).

Клиенту — «Заявка опубликована» после ручной проверки; исполнителю — исходы в центре S42 без
бота: «Клиент отклонил отклик» и «Сделка выполнена». Новый CHECK — надмножество старого, длина
varchar (30) не меняется. DROP → ADD … NOT VALID → VALIDATE после commit, как в
notifications_0005. Downgrade удаляет строки новых типов.

Ревизия: notifications_0009 (2026-10-05 21:40:00.000000+00:00)
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
ADDED = ("job.published", "response.declined", "deal.completed")
NEW = OLD + "".join(f", '{type_}'" for type_ in ADDED)


def _types(values: str) -> None:
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CHECK}")
    op.execute(f"ALTER TABLE {TABLE} ADD CONSTRAINT {CHECK} CHECK (type IN ({values})) NOT VALID")
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CHECK}")


def upgrade() -> None:
    _types(NEW)


def downgrade() -> None:
    added = ", ".join(f"'{type_}'" for type_ in ADDED)
    op.execute(
        "DELETE FROM notifications.deliveries WHERE notification_id IN"
        f" (SELECT id FROM notifications.notifications WHERE type IN ({added}))"
    )
    op.execute(f"DELETE FROM notifications.notifications WHERE type IN ({added})")
    _types(OLD)
