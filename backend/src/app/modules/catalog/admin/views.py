"""Справочник категорий в админке (DEVELOPMENT_PLAN 2.7b; ADR-0020 §1, §4).

Правятся настройки, которые сид не задаёт или задаёт только при вставке (writer.py):
включена ли категория и тег, заявки и предел откликов, риск для модерации, порядок и иконка.
Названия, дерево и словарь поиска принадлежат сидам (`cli seed`; seed_hash не меняется правкой,
поэтому сид перепишет категорию, только если изменится она сама в сиде) — в админке они только
для чтения; правка переводов из админки — следующим шагом вместе с формой LocalizedText.

Каждая правка: тот же advisory lock, что импорт `cli seed`; аудит; CatalogChanged (переиндексация
поиска); снимок таксономии этого процесса сбрасывается сразу, у остальных — за TTL (60 с).
"""

from collections.abc import Iterable
from datetime import datetime
from typing import Any, ClassVar, override

from starlette.requests import Request

from app.modules.catalog.application.ports import TaxonomyCache
from app.modules.catalog.infrastructure.models import (
    IMPORT_LOCK,
    CategoryRow,
    SearchTermRow,
    TagRow,
)
from app.platform.contracts.events.catalog import CatalogChanged
from app.platform.http.admin import ADMIN, StaffModelView, container_of
from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import CategoryId


class _CatalogView(StaffModelView):
    roles = ADMIN
    advisory_lock = IMPORT_LOCK
    category = "Справочники"
    can_create = can_delete = False

    def changed_category(self, model: Any) -> int:
        raise NotImplementedError

    @override
    def change_events(self, model: Any, now: datetime) -> Iterable[DomainEvent]:
        return (
            CatalogChanged(
                category_ids=(CategoryId(self.changed_category(model)),), occurred_at=now
            ),
        )

    @override
    async def after_change(self, model: Any, request: Request) -> None:
        (await container_of(request).get(TaxonomyCache)).invalidate()


class CategoryAdmin(_CatalogView, model=CategoryRow):
    name = "Категория"
    name_plural = "Категории"
    icon = "fa-solid fa-sitemap"
    audit_entity = "catalog.category"
    column_list: ClassVar[Any] = [
        CategoryRow.id,
        CategoryRow.slug,
        CategoryRow.name,
        CategoryRow.depth,
        CategoryRow.is_active,
        CategoryRow.jobs_enabled,
        CategoryRow.max_responses,
        CategoryRow.risk_level,
        CategoryRow.sort_order,
    ]
    column_searchable_list: ClassVar[Any] = [CategoryRow.slug]
    column_sortable_list: ClassVar[Any] = [CategoryRow.id, CategoryRow.slug, CategoryRow.sort_order]
    form_columns: ClassVar[Any] = [
        CategoryRow.is_active,
        CategoryRow.jobs_enabled,
        CategoryRow.max_responses,
        CategoryRow.risk_level,
        CategoryRow.sort_order,
        CategoryRow.icon,
    ]

    def changed_category(self, model: Any) -> int:
        return int(model.id)


class TagAdmin(_CatalogView, model=TagRow):
    name = "Тег"
    name_plural = "Теги"
    icon = "fa-solid fa-tag"
    audit_entity = "catalog.tag"
    column_list: ClassVar[Any] = [
        TagRow.id,
        TagRow.category_id,
        TagRow.slug,
        TagRow.name,
        TagRow.is_active,
    ]
    column_searchable_list: ClassVar[Any] = [TagRow.slug]
    form_columns: ClassVar[Any] = [TagRow.is_active]

    def changed_category(self, model: Any) -> int:
        return int(model.category_id)


class SearchTermAdmin(_CatalogView, model=SearchTermRow):
    """Словарь поиска — целиком из сида (при изменении категории её строки заменяются), поэтому
    только для чтения: правка здесь пропала бы на следующем `cli seed`."""

    name = "Поисковый термин"
    name_plural = "Поисковые термины"
    icon = "fa-solid fa-magnifying-glass"
    audit_entity = "catalog.search_term"
    can_edit = False
    column_list: ClassVar[Any] = [
        SearchTermRow.id,
        SearchTermRow.term,
        SearchTermRow.lang,
        SearchTermRow.category_id,
        SearchTermRow.tag_id,
        SearchTermRow.weight,
    ]
    column_searchable_list: ClassVar[Any] = [SearchTermRow.term]

    def changed_category(self, model: Any) -> int:
        return int(model.category_id)


VIEWS = (CategoryAdmin, TagAdmin, SearchTermAdmin)
