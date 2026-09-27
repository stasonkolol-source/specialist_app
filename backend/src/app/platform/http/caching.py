"""Кэшируемые публичные ответы (ARCHITECTURE §8.1): сильный ETag по телу, If-None-Match → 304.

Тело сериализуется детерминированно (ключи по порядку), ETag — первые 128 бит SHA-256.
Совпадение ищется слабым сравнением RFC 9110 (префикс `W/` не мешает), `*` совпадает с
любым телом. Ответ, зависящий от языка, передаёт `vary="Accept-Language"`.
"""

import hashlib
import json
from typing import Any

from fastapi import Request, Response

NOT_MODIFIED: dict[int | str, dict[str, Any]] = {
    304: {"description": "Не изменилось (If-None-Match)"}
}
"""`responses=` обработчика: 304 в OpenAPI."""


def cached_json(
    request: Request, body: object, *, max_age: int, vary: str | None = None
) -> Response:
    raw = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    etag = f'"{hashlib.sha256(raw).hexdigest()[:32]}"'
    headers = {"ETag": etag, "Cache-Control": f"public, max-age={max_age}"}
    if vary is not None:
        headers["Vary"] = vary
    if matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return Response(raw, media_type="application/json", headers=headers)


def matches(if_none_match: str | None, etag: str) -> bool:
    tags = {part.strip().removeprefix("W/") for part in (if_none_match or "").split(",")}
    return etag in tags or "*" in tags
