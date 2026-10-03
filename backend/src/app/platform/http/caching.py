"""Кэшируемые публичные ответы (ARCHITECTURE §8.1): сильный ETag по телу, If-None-Match → 304.

Тело сериализуется детерминированно (ключи по порядку), ETag — первые 128 бит SHA-256.
Совпадение ищется слабым сравнением RFC 9110 (префикс `W/` не мешает), `*` совпадает с
любым телом. Ответ, зависящий от языка, передаёт `vary="Accept-Language"`.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from fastapi import Request, Response

NOT_MODIFIED: dict[int | str, dict[str, Any]] = {
    304: {"description": "Не изменилось (If-None-Match)"}
}
"""`responses=` обработчика: 304 в OpenAPI."""
DICTIONARY_SWR = 86400
"""Справочники (города, районы, категории) меняются редко: сутки клиент может показывать
прошлый ответ, пока проверяет новый в фоне (`stale-while-revalidate`)."""


@dataclass(frozen=True, slots=True)
class EncodedJson:
    """Тело ответа и его ETag: справочник строит их раз на снимок (platform/cache/memo.py)."""

    raw: bytes
    etag: str


def encode_json(body: object) -> EncodedJson:
    raw = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return EncodedJson(raw=raw, etag=f'"{hashlib.sha256(raw).hexdigest()[:32]}"')


def cached_json(
    request: Request,
    body: object,
    *,
    max_age: int,
    vary: str | None = None,
    stale_while_revalidate: int | None = None,
) -> Response:
    return cached_response(
        request,
        encode_json(body),
        max_age=max_age,
        vary=vary,
        stale_while_revalidate=stale_while_revalidate,
    )


def cached_response(
    request: Request,
    encoded: EncodedJson,
    *,
    max_age: int,
    vary: str | None = None,
    stale_while_revalidate: int | None = None,
) -> Response:
    control = f"public, max-age={max_age}"
    if stale_while_revalidate is not None:
        control += f", stale-while-revalidate={stale_while_revalidate}"
    headers = {"ETag": encoded.etag, "Cache-Control": control}
    if vary is not None:
        headers["Vary"] = vary
    if matches(request.headers.get("if-none-match"), encoded.etag):
        return Response(status_code=304, headers=headers)
    return Response(encoded.raw, media_type="application/json", headers=headers)


def matches(if_none_match: str | None, etag: str) -> bool:
    tags = {part.strip().removeprefix("W/") for part in (if_none_match or "").split(",")}
    return etag in tags or "*" in tags
