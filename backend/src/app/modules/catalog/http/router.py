"""HTTP catalog 🔓 (DEVELOPMENT_PLAN 1.3b): дерево категорий с ETag."""

from typing import Annotated

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Query, Request, Response

from app.modules.catalog.application.dto import CategoryView
from app.modules.catalog.application.ports import CatalogQuery
from app.modules.catalog.http.schemas import CategoryOut
from app.platform.http.caching import (
    DICTIONARY_SWR,
    NOT_MODIFIED,
    EncodedJson,
    cached_response,
    encode_json,
)
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
    # тело и ETag — раз на снимок дерева, язык и город с ориентирами; город без ориентиров
    # даёт то же тело, что и без города, — один ключ (мусорные slug не раздувают память)
    memo = await query.representations()
    known = city if city is not None and city in await query.price_hint_cities() else None
    tree = await query.tree()
    body = memo.get((locale, known), lambda: _tree(tree, locale, city))
    return cached_response(
        request,
        body,
        max_age=MAX_AGE_SECONDS,
        vary="Accept-Language",
        stale_while_revalidate=DICTIONARY_SWR,
    )


def _tree(tree: list[CategoryView], locale: Locale, city: str | None) -> EncodedJson:
    return encode_json(
        [CategoryOut.of(node, locale, city).model_dump(mode="json") for node in tree]
    )
