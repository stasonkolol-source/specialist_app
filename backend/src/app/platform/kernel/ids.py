"""Идентификаторы сущностей: UUIDv7 (ARCHITECTURE §7.1, ADR-0020 §2).

UUIDv7 сортируется по времени создания и безопасен для выдачи наружу. Типизированные ID
модули объявляют через NewType (`JobId = NewType("JobId", UUID)`) и создают как
`JobId(new_id())`.
"""

import uuid
from typing import NewType
from uuid import UUID

UserId = NewType("UserId", UUID)
"""Внутренний идентификатор пользователя — он же `sub` в JWT и `user_id` в логах."""

CityId = NewType("CityId", int)
DistrictId = NewType("DistrictId", int)
"""Справочники geo — int identity (ARCHITECTURE §7.3): их id видят фасады и API."""


def new_id() -> UUID:
    """Новый UUIDv7. Монотонен в пределах процесса (счётчик внутри миллисекунды)."""
    return uuid.uuid7()


def parse_id(value: str) -> UUID:
    """Разобрать строковый UUID; ValueError, если строка — не UUID."""
    return UUID(value)
