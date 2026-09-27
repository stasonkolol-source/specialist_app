"""GET /client-config 🔓 (DEVELOPMENT_PLAN 1.1, ARCHITECTURE §8.5): что клиент читает при старте.

Минимальные версии (426), публичные флаги (сегмент «Вещи» и т. п.), версии правовых
документов. Ответ одинаков для всех, поэтому кэшируется: ETag + If-None-Match → 304.
"""

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from app.platform.config.cache import ClientConfigCache
from app.platform.http.caching import NOT_MODIFIED, cached_json
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
    responses=NOT_MODIFIED,
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
    return cached_json(request, body, max_age=MAX_AGE_SECONDS)
