"""reviews_0005: отзывы сделок, оставленные до публикации профиля исполнителя, — к его профилю
(UXM-12).

Сделка запоминала профиль исполнителя, только если он уже опубликован, и отзыв брал профиль
из сделки: кто работал, пока профиль ждал проверки, получал отзывы с пустым
`subject_profile_id` — карточка оставалась «Новый специалист». Новые отзывы теперь привязывает
подписчик ProfilePublished (`reviews.attach_profile`); миграция привязывает уже оставленные —
к живому опубликованному профилю того же человека. Рейтинг пересчитает ночной
`reviews.recompute_ratings`: он берёт и профили с опубликованными отзывами без строки рейтинга.
Откат не нужен: отвязать отзывы значило бы снова спрятать рейтинг — downgrade ничего не делает.

Ревизия: reviews_0005 (2026-10-05 21:00:00.000000+00:00)
Предыдущая: platform_0007

Правила (DEVELOPMENT_PLAN 0.9, ADR-0005):
- имя ревизии — <модуль>_NNNN, файл — <модуль>_NNNN_<slug>.py;
- миграции идут под ролью migrator: lock_timeout = 3s задан роли, долгих блокировок нет;
- индексы на живых таблицах — CREATE INDEX CONCURRENTLY внутри op.get_context().autocommit_block();
- expand/contract: сначала добавить (nullable, новая колонка, двойная запись), удалять — отдельной
  миграцией после выкладки кода, который старое больше не читает.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "reviews_0005"
down_revision: str | Sequence[str] | None = "platform_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # строк — единицы (только до первого профиля исполнителя): одним UPDATE, без батчей
    op.execute(
        """
        UPDATE reviews.reviews AS r
           SET subject_profile_id = p.id, version = r.version + 1
          FROM specialists.profiles AS p
         WHERE r.subject_profile_id IS NULL
           AND r.kind = 'deal'
           AND r.direction = 'client_to_performer'
           AND p.user_id = r.subject_user_id
           AND p.deleted_at IS NULL
           AND p.status = 'published'
        """
    )


def downgrade() -> None:
    pass
