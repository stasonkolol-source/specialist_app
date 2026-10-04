"""Admin API catalog (DEVELOPMENT_PLAN 2.7b, часть 2; ARCHITECTURE §8.5): категории, теги, словарь.

Только admin. Правится то же, что в разделах SQLAdmin (admin/views.py), и тем же путём —
`apply_change` с хуками раздела: поля `form_columns`, название формой LocalizedText (правка
ставит `name_origin = admin`, `cli seed` его больше не переписывает), advisory lock импорта,
аудит `catalog.category|tag.updated`, CatalogChanged (переиндексация поиска) и сброс снимка
таксономии. Дерево, слаги и словарь поиска принадлежат сидам: поисковые термины — только чтение.
"""

from typing import Annotated, Any

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.admin.views import CategoryAdmin, SearchTermAdmin, TagAdmin
from app.platform.http.admin import ADMIN, AdminRows, apply_change, as_row, table_of
from app.platform.http.pagination import PageOut, PageParams
from app.platform.http.staff import staff_only
from app.platform.kernel.errors import NotFoundError
from app.platform.kernel.localized import Locale

router = APIRouter(tags=["catalog"])

MAX_NAME = 120
NameIn = dict[Locale, Annotated[str, Field(max_length=MAX_NAME)]]


class CategoryOut(BaseModel):
    id: int
    parent_id: int | None
    slug: str
    name: dict[str, str]
    name_origin: str = Field(description="seed — название ведёт сид, admin — админка")
    depth: int
    icon: str | None
    sort_order: int
    is_active: bool
    jobs_enabled: bool
    max_responses: int
    risk_level: int

    @classmethod
    def of(cls, row: Any) -> CategoryOut:
        return cls(**_plain(row, cls), name=row["name"].to_mapping())


class CategoryPatchIn(BaseModel):
    """Поля, которые сид не задаёт или задаёт только новой строке (как форма SQLAdmin)."""

    is_active: Annotated[bool | None, Query()] = None
    jobs_enabled: bool | None = None
    max_responses: int | None = Field(default=None, ge=0)
    risk_level: int | None = Field(default=None, ge=0)
    sort_order: int | None = None
    icon: str | None = Field(default=None, max_length=32)
    name: NameIn | None = Field(
        default=None,
        description="Локали поверх текущего названия; ru и sr-Cyrl обязательны, пустая sr-Latn —"
        " транслит sr-Cyrl",
    )


class TagOut(BaseModel):
    id: int
    category_id: int
    slug: str
    name: dict[str, str]
    name_origin: str
    is_active: bool

    @classmethod
    def of(cls, row: Any) -> TagOut:
        return cls(**_plain(row, cls), name=row["name"].to_mapping())


class TagPatchIn(BaseModel):
    is_active: Annotated[bool | None, Query()] = None
    name: NameIn | None = None


class SearchTermOut(BaseModel):
    id: int
    term: str
    lang: str
    category_id: int
    tag_id: int | None
    weight: float

    @classmethod
    def of(cls, row: Any) -> SearchTermOut:
        return cls(**_plain(row, cls))


@router.get("/categories", response_model=PageOut[CategoryOut], **staff_only(ADMIN))
@inject
async def list_categories(
    page: PageParams,
    session: FromDishka[AsyncSession],
    parent_id: int | None = None,
    is_active: Annotated[bool | None, Query()] = None,
) -> PageOut[CategoryOut]:
    table = table_of(CategoryAdmin)
    where = []
    if parent_id is not None:
        where.append(table.c.parent_id == parent_id)
    if is_active is not None:
        where.append(table.c.is_active.is_(is_active))
    found = await AdminRows(session).page(table, page, *where)
    return PageOut.of(found, CategoryOut.of)


@router.patch("/categories/{category_id}", response_model=CategoryOut, **staff_only(ADMIN))
async def update_category(category_id: int, body: CategoryPatchIn, request: Request) -> CategoryOut:
    """Правка категории: аудит, CatalogChanged и сброс снимка таксономии — как в SQLAdmin."""
    model = await apply_change(
        request,
        CategoryAdmin(),
        category_id,
        body.model_dump(exclude_unset=True, exclude={"name"}),
        name=body.name,
    )
    if model is None:
        raise NotFoundError(category_id=category_id)
    return CategoryOut.of(as_row(model))


@router.get("/tags", response_model=PageOut[TagOut], **staff_only(ADMIN))
@inject
async def list_tags(
    page: PageParams,
    session: FromDishka[AsyncSession],
    category_id: int | None = None,
    is_active: Annotated[bool | None, Query()] = None,
) -> PageOut[TagOut]:
    table = table_of(TagAdmin)
    where = []
    if category_id is not None:
        where.append(table.c.category_id == category_id)
    if is_active is not None:
        where.append(table.c.is_active.is_(is_active))
    return PageOut.of(await AdminRows(session).page(table, page, *where), TagOut.of)


@router.patch("/tags/{tag_id}", response_model=TagOut, **staff_only(ADMIN))
async def update_tag(tag_id: int, body: TagPatchIn, request: Request) -> TagOut:
    """Включить или выключить тег, поправить название; CatalogChanged — по его категории."""
    model = await apply_change(
        request,
        TagAdmin(),
        tag_id,
        body.model_dump(exclude_unset=True, exclude={"name"}),
        name=body.name,
    )
    if model is None:
        raise NotFoundError(tag_id=tag_id)
    return TagOut.of(as_row(model))


@router.get("/search-terms", response_model=PageOut[SearchTermOut], **staff_only(ADMIN))
@inject
async def list_search_terms(
    page: PageParams,
    session: FromDishka[AsyncSession],
    category_id: int | None = None,
    q: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
) -> PageOut[SearchTermOut]:
    """Словарь поиска — только чтение: его заменяет сид целиком при изменении категории."""
    table = table_of(SearchTermAdmin)
    where = []
    if category_id is not None:
        where.append(table.c.category_id == category_id)
    if q:
        where.append(table.c.term.icontains(q, autoescape=True))
    return PageOut.of(await AdminRows(session).page(table, page, *where), SearchTermOut.of)


def _plain(row: Any, schema: type[BaseModel]) -> dict[str, Any]:
    """Поля схемы из строки, кроме названия; перечисления — значениями."""
    return {
        key: getattr(row[key], "value", row[key]) for key in schema.model_fields if key != "name"
    }
