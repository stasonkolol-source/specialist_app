"""Контракт модуля specialists для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из specialists только этот файл. Модерация (выше по DAG) проверяет
профиль через адаптер цели: читает текст и публикует или возвращает на правки.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.specialists.errors import ProfileNotFoundError as ProfileNotFoundError
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileForReview:
    """Что проверяет модерация: текст профиля без контактов автора не очищен — это делает
    конвейер (ai/prompt.py)."""

    user_id: UserId
    text: str
    """Имя, «коротко о себе» и «о себе» — одним текстом."""
    version: int
    first_review: bool
    """Новый профиль или переход в «Специалист»: проверяет человек (P2, §14.1)."""
    risk_level: int
    """Самый строгий риск категорий профиля (catalog)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileRef:
    """Профиль пользователя для модулей выше по DAG (прайс, портфолио)."""

    id: UUID
    kind: str
    status: str


class PriceList(Protocol):
    """Прайс профиля — его ведёт pricing (выше по DAG): specialists спрашивает через этот порт,
    pricing реализует, связывает dishka (как LegalHold у media)."""

    async def has_items(self, profile_id: UUID) -> bool:
        """Есть ли видимая позиция прайса: без неё «Специалиста» на проверку не отправить."""
        ...


class SpecialistsApi(Protocol):
    async def profile_of(self, user_id: UserId) -> ProfileRef | None:
        """Профиль пользователя; None — его нет (или удалён)."""
        ...

    async def profile_for_review(self, profile_id: UUID) -> ProfileForReview | None:
        """Профиль на проверке или опубликованный (пост-модерация правок); None — нет такого,
        удалён или проверять нечего (черновик, приостановлен)."""
        ...

    async def approve_profile(self, profile_id: UUID, *, version: int | None) -> None:
        """Проверка пройдена — в транзакции вызывающего: ждавший проверки публикуется;
        другая версия или статус — ничего."""
        ...

    async def reject_profile(self, profile_id: UUID, *, reason_code: str) -> None:
        """Нарушение — в транзакции вызывающего: ждавший проверки возвращается на правки,
        опубликованный приостанавливается."""
        ...
