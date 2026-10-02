"""Keyset-пагинация (ADR-0003): курсор непрозрачен для клиента."""

from dataclasses import dataclass

from app.platform.kernel.errors import DomainValidationError

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class InvalidCursorError(DomainValidationError):
    """Курсор не разобрать: битый или подделан (422)."""

    code = "invalid_cursor"


@dataclass(frozen=True, slots=True, kw_only=True)
class PageRequest:
    limit: int = DEFAULT_LIMIT
    cursor: str | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= MAX_LIMIT:
            raise DomainValidationError(field="limit", value=self.limit, max=MAX_LIMIT)


@dataclass(frozen=True, slots=True, kw_only=True)
class Page[T]:
    items: tuple[T, ...]
    next_cursor: str | None = None

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None
