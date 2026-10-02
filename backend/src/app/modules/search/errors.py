"""Ошибки модуля search со стабильными code (ADR-0020 §9)."""

from app.platform.kernel.errors import ConflictError


class FavoritesFullError(ConflictError):
    """В избранном уже максимум записей этого типа."""

    code = "favorites_full"
    public_params = ("limit",)
