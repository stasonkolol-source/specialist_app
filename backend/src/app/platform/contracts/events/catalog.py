"""События модуля catalog (ADR-0020 §2, ARCHITECTURE §5.3)."""

from dataclasses import dataclass

from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import CategoryId


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogChanged(DomainEvent):
    """Изменился справочник категорий: названия, дерево (`path`), теги или словарь поиска.

    Публикуют импорт сидов и правка в админке (2.7b); подписчик — переиндексация поиска (4.1).
    `category_ids` — изменённые категории; их потомки перечислены, если у них сменился `path`.
    """

    event_type = "catalog.CatalogChanged"
    category_ids: tuple[CategoryId, ...]
