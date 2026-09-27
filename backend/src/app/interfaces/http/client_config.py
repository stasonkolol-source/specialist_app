"""GET /client-config 🔓 (DEVELOPMENT_PLAN 1.1, ARCHITECTURE §8.5): что клиент читает при старте.

Минимальные версии (426), публичные флаги (сегмент «Вещи» и т. п.), версии правовых
документов. Ответ одинаков для всех, поэтому кэшируется: ETag + If-None-Match → 304.
"""

import hashlib
import json

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from app.platform.config.cache import ClientConfigCache
from app.platform.settings import AppSettings

router = APIRouter(tags=["platform"])
MAX_AGE_SECONDS = 60


class ClientConfigOut(BaseModel):
    min_versions: dict[str, str]
    """Минимальная версия клиента по платформе (tma, ios, android): старше — 426."""
    flags: dict[str, bool]
    legal_versions: dict[str, str]
    """Действующие версии правовых документов (terms, privacy): клиент сверяет согласие."""


@router.get(
    "/client-config",
    response_model=ClientConfigOut,
    responses={304: {"description": "Не изменилось (If-None-Match)"}},
)
@inject
async def get_client_config(
    request: Request, cache: FromDishka[ClientConfigCache], app: FromDishka[AppSettings]
) -> Response:
    snapshot = await cache.get()
    body = ClientConfigOut(
        min_versions={**app.min_client_versions, **snapshot.min_versions},
        flags=snapshot.public_flags(),
        legal_versions=dict(snapshot.legal_versions),
    ).model_dump(mode="json")
    raw = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    etag = f'"{hashlib.sha256(raw).hexdigest()[:32]}"'
    headers = {"ETag": etag, "Cache-Control": f"public, max-age={MAX_AGE_SECONDS}"}
    if etag in _etags(request.headers.get("if-none-match")):
        return Response(status_code=304, headers=headers)
    return Response(raw, media_type="application/json", headers=headers)


def _etags(header: str | None) -> set[str]:
    return {part.strip().removeprefix("W/") for part in (header or "").split(",") if part.strip()}
