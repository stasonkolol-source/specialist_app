"""Избранное (DEVELOPMENT_PLAN 4.6; ARCHITECTURE §7.3 `search.favorites`): «мои мастера».
Специалист в избранном показывается, пока виден в каталоге: скрытый или снятый профиль из списка
пропадает, но запись остаётся до удаления аккаунта. Сохранённые заявки (5.3) живут в модуле jobs
(`jobs.saved_jobs`): карточка и видимость заявки — у него; тип JOB здесь не используется.
"""

from enum import StrEnum
from typing import Final


class FavoriteType(StrEnum):
    PROFILE = "profile"
    JOB = "job"


MAX_FAVORITES: Final = 100
"""Записей одного типа: в S12 больше не листают, а выше — уже скрипт."""
