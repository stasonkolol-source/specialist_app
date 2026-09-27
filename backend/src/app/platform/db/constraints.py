"""Перевод нарушений ограничений БД в доменные ошибки по имени constraint (ADR-0020 §5).

Ошибки всплывают на flush в репозитории: там же они и переводятся. Неизвестное
ограничение пробрасывается как есть — это ошибка программиста, а не пользователя.
"""

from collections.abc import Callable, Mapping
from typing import NoReturn

from sqlalchemy.exc import IntegrityError

from app.platform.kernel.errors import DomainError

ConstraintErrors = Mapping[str, Callable[[], DomainError]]


def constraint_name(error: IntegrityError) -> str | None:
    """Имя нарушенного ограничения из диагностики psycopg."""
    diag = getattr(error.orig, "diag", None)
    name = getattr(diag, "constraint_name", None)
    return str(name) if name else None


def raise_domain_error(error: IntegrityError, mapping: ConstraintErrors) -> NoReturn:
    """Бросить доменную ошибку по имени constraint или исходную IntegrityError."""
    name = constraint_name(error)
    factory = mapping.get(name) if name else None
    if factory is None:
        raise error
    raise factory() from error
