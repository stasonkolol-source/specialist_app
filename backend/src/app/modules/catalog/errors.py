"""Ошибки модуля catalog со стабильными code (ADR-0020 §9)."""

from app.platform.kernel.errors import DomainValidationError


class CategoryTooDeepError(DomainValidationError):
    """Дерево категорий глубже MAX_DEPTH уровней (ARCHITECTURE §7.5): CHECK в БД.

    Параметры: `max_depth`; импорт сидов добавляет `slug` категории, которая оказалась бы
    глубже, — в том числе категории, которой в сиде уже нет.
    """

    code = "category_too_deep"
