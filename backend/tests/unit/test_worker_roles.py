"""Роли воркера (DEVELOPMENT_PLAN 0.12, 2.3b; ARCHITECTURE §12.2): у очереди свой пул.

Рассылка уведомлений ждёт слотов лимитера Telegram: в общем пуле она заняла бы места
обработчиков событий и периодических задач (heartbeat), и воркер казался бы мёртвым.
"""

import pytest

from app.entrypoints.worker import ROLES
from app.platform.queue.tasks import QUEUES

pytestmark = pytest.mark.unit


def test_every_queue_has_its_own_pool() -> None:
    pools = [pool for role in ROLES.values() for pool in role]

    assert sorted(pool.queue for pool in pools) == sorted(QUEUES)
    assert {pool.queue: pool.concurrency for pool in ROLES["worker"]} == {
        "default": 8,
        "notifications": 4,  # §12.2
    }
