"""Оптимистичная блокировка в HTTP (ARCHITECTURE §8.1): `If-Match: "<version>"` → 412.

Ответ с версионируемым агрегатом несёт `ETag: "<version>"`; клиент отправляет его в
`If-Match` при изменении. Use case передаёт версию в `aggregate.ensure_version(...)`,
несовпадение — StaleVersionError (412). Нет заголовка или `*` — версию не сверяем:
параллельную запись всё равно ловит version_id_col (409 `concurrent_modification`).
"""

import re
from typing import Annotated

from fastapi import Depends, Header, Response

from app.platform.kernel.errors import DomainValidationError

_VERSION = re.compile(r'"(\d{1,18})"')


class InvalidIfMatchError(DomainValidationError):
    code = "invalid_if_match"


def if_match(
    header: Annotated[str | None, Header(alias="If-Match", include_in_schema=True)] = None,
) -> int | None:
    if header is None or header.strip() == "*":
        return None
    match = _VERSION.fullmatch(header.strip())
    if match is None:
        raise InvalidIfMatchError
    return int(match[1])


IfMatch = Annotated[int | None, Depends(if_match)]
"""Параметр обработчика изменения: `expected_version: IfMatch`."""


def etag(version: int) -> str:
    return f'"{version}"'


def set_etag(response: Response, version: int) -> None:
    response.headers["ETag"] = etag(version)
