"""DTO модуля moderation (ADR-0020 §6)."""

from dataclasses import dataclass
from uuid import UUID

from app.platform.ai.port import ContentKind
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ContentCheck:
    """Текст на проверку правилами: заявка, отклик, сообщение, профиль или отзыв."""

    author_id: UserId
    kind: ContentKind
    content_id: UUID
    """Повторная проверка той же единицы контента не увеличивает счётчики velocity."""
    text: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportRulesResult:
    """Счётчики импорта словаря из сидов (`cli seed`)."""

    created: int
    updated: int
    unchanged: int
    deactivated: int
    """Правила сида, которых больше нет в файле: выключены, строки остались для истории."""
    skipped: int
    """В файле, но в БД такое правило завела админка: его не трогаем."""
