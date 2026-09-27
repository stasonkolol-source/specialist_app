"""Повтор команды при конфликте параллельной записи (platform/db/retry.py)."""

import pytest

from app.platform.db.retry import CONFLICT_ATTEMPTS, retry_on_conflict
from app.platform.kernel.errors import ConcurrentModificationError, ConflictError

pytestmark = pytest.mark.unit


class Command:
    def __init__(self, conflicts: int, error: Exception | None = None) -> None:
        self.calls = 0
        self.conflicts = conflicts
        self.error = error

    async def __call__(self) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if self.calls <= self.conflicts:
            raise ConcurrentModificationError()
        return "ok"


async def test_repeats_until_the_command_passes() -> None:
    command = Command(conflicts=CONFLICT_ATTEMPTS - 1)

    assert await retry_on_conflict(command) == "ok"
    assert command.calls == CONFLICT_ATTEMPTS


async def test_gives_up_after_all_attempts() -> None:
    command = Command(conflicts=CONFLICT_ATTEMPTS)

    with pytest.raises(ConcurrentModificationError):
        await retry_on_conflict(command)
    assert command.calls == CONFLICT_ATTEMPTS


async def test_other_errors_are_not_repeated() -> None:
    command = Command(conflicts=0, error=ConflictError())

    with pytest.raises(ConflictError):
        await retry_on_conflict(command)
    assert command.calls == 1
