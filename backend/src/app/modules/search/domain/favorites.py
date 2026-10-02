"""Избранное (DEVELOPMENT_PLAN 4.6; ARCHITECTURE §7.3 `search.favorites`): «мои мастера» и — с
шагом 5.3 — сохранённые заявки. Специалист в избранном показывается, пока виден в каталоге:
скрытый или снятый профиль из списка пропадает, но запись остаётся до удаления аккаунта.
"""

from enum import StrEnum
from typing import Final


class FavoriteType(StrEnum):
    PROFILE = "profile"
    JOB = "job"


MAX_FAVORITES: Final = 100
"""Записей одного типа: в S12 больше не листают, а выше — уже скрипт."""
