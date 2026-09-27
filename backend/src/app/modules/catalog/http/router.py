"""HTTP catalog 🔓 (DEVELOPMENT_PLAN 1.3b): дерево категорий с ETag."""

from typing import Annotated

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Query, Request, Response

from app.modules.catalog.application.ports import CatalogQuery
from app.modules.catalog.http.schemas import CategoryOut
from app.platform.http.caching import NOT_MODIFIED, cached_json
from app.platform.kernel.localized import Locale

router = APIRouter(tags=["catalog"])
MAX_AGE_SECONDS = 300
CITY_SLUG = r"^[a-z0-9]+(-[a-z0-9]+)*$"


@router.get("/categories", response_model=list[CategoryOut], responses=NOT_MODIFIED)
@inject
async def list_categories(
    request: Request,
    query: FromDishka[CatalogQuery],
    locale: FromDishka[Locale],
    city: Annotated[
        str | None,
        Query(max_length=64, pattern=CITY_SLUG, description="slug города для price_hint"),
    ] = None,
) -> Response:
    """Дерево категорий на языке Accept-Language; ETag + If-None-Match → 304.

    Неизвестный город — не ошибка: у категорий просто нет ориентира цены.
    """
    body = [
        CategoryOut.of(node, locale, city).model_dump(mode="json") for node in await query.tree()
    ]
    return cached_json(request, body, max_age=MAX_AGE_SECONDS, vary="Accept-Language")
