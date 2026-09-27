"""Ошибки модуля catalog со стабильными code (ADR-0020 §9)."""

from app.platform.kernel.errors import DomainValidationError


class CategoryTooDeepError(DomainValidationError):
    """Дерево категорий глубже MAX_DEPTH уровней (ARCHITECTURE §7.5): CHECK в БД."""

    code = "category_too_deep"
