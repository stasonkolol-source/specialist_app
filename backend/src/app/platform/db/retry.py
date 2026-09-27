"""Повтор команды при конфликте параллельной записи (ADR-0020 §9).

`ConcurrentModificationError` значит: строку изменил параллельный запрос, пока мы её читали.
Для идемпотентных по смыслу команд (вход, запись факта) правильный ответ — перечитать и
повторить, а не показывать человеку ошибку. Каждая попытка — новая транзакция: UoW после
отката пуст, события прошлой попытки не уходят.
"""

from collections.abc import Awaitable, Callable

import structlog

from app.platform.kernel.errors import ConcurrentModificationError

log = structlog.get_logger(__name__)

CONFLICT_ATTEMPTS = 3


async def retry_on_conflict[T](
    command: Callable[[], Awaitable[T]], *, attempts: int = CONFLICT_ATTEMPTS
) -> T:
    """Выполнить `command`, повторяя при конфликте; после `attempts` попыток — ошибка как есть."""
    for attempt in range(1, attempts):
        try:
            return await command()
        except ConcurrentModificationError as exc:
            log.info("command_conflict_retry", attempt=attempt, code=exc.code)
    return await command()
