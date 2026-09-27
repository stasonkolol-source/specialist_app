"""Курсорная пагинация в HTTP (ARCHITECTURE §8.4): `?limit=20&cursor=…` → `{items, next_cursor}`.

Курсор — base64url от ключа сортировки `(sort_key, id)`; его строит и разбирает
query-сервис (platform/db/query.py: encode_cursor / decode_cursor). Битый курсор —
InvalidCursorError (422 `invalid_cursor`).
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel

from app.platform.kernel.pagination import DEFAULT_LIMIT, MAX_LIMIT, Page, PageRequest

MAX_CURSOR_LENGTH = 512


class PageOut[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None

    @classmethod
    def of[S](cls, page: Page[S], convert: Callable[[S], T]) -> PageOut[T]:
        return cls(items=[convert(item) for item in page.items], next_cursor=page.next_cursor)


def page_request(
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(min_length=1, max_length=MAX_CURSOR_LENGTH)] = None,
) -> PageRequest:
    return PageRequest(limit=limit, cursor=cursor)


PageParams = Annotated[PageRequest, Depends(page_request)]
"""Параметр обработчика списка: `async def list_jobs(page: PageParams) -> PageOut[JobOut]`."""
