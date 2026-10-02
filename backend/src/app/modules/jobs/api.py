"""Контракт модуля jobs для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из jobs только этот файл.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.platform.kernel.ids import MediaId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class JobForReview:
    """Заявка для конвейера модерации (адаптер цели `job`, §14.1)."""

    client_id: UserId
    text: str
    """Заголовок и описание — то, что увидят исполнители."""
    version: int
    media_ids: tuple[MediaId, ...]
    risk_level: int
    """Риск категории: `≥ 1` — заявку проверяет человек (P2)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class JobBrief:
    """Заявка для уведомлений клиенту о её сроке (`job.expiring`, `job.expired`)."""

    client_id: UserId
    title: str
    status: str
    """Статус заявки (`published`, `expired`, …): уведомление о сроке нужно, только пока она
    в ожидаемом статусе."""
    expires_at: datetime | None
    can_extend: bool
    """Продлевали меньше трёх раз — кнопка «Продлить» имеет смысл."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ResponseForReview:
    """Отклик для конвейера модерации (адаптер цели `response`, §14.1)."""

    performer_id: UserId
    text: str
    """Сообщение клиенту и «когда смогу» — то, что увидит клиент."""
    revision: int
    """Редакция, которую проверяют: публикация устаревшей — ничего."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ResponsesNotice:
    """Отклики на заявку для уведомления клиенту `response.received` (5.4)."""

    client_id: UserId
    title: str
    status: str
    unseen: int
    """Видимые клиенту отклики, которые он ещё не открыл (проверка пройдена, «отправлен»)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class TemplateRef:
    """Шаблон отклика для кнопки «Откликнуться шаблоном» в уведомлении."""

    id: UUID
    title: str


@dataclass(frozen=True, slots=True, kw_only=True)
class InviteNotice:
    """Приглашение для уведомления специалисту `job.invited` (5.6)."""

    title: str
    status: str
    client_name: str | None
    """Как подписан клиент («Елена К.»); аккаунт удалён — None."""
    templates: tuple[TemplateRef, ...]
    """Шаблоны приглашённого по порядку — кнопки; уже откликнулся — пусто."""


@dataclass(frozen=True, slots=True, kw_only=True)
class OwnerResponseView:
    """Отклик на заявку для её владельца (S23): только прошедшие проверку."""

    id: UUID
    performer_id: UserId
    profile_id: UUID | None
    """Профиль специалиста; без него — подработка."""
    status: str
    message: str
    price_type: str
    price_amount: int | None
    availability_note: str | None
    is_first: bool
    is_new: bool
    """Клиент его ещё не видел: прошёл проверку или поправлен после прошлого просмотра."""
    created_at: datetime


class JobsApi(Protocol):
    async def job_for_review(self, job_id: UUID) -> JobForReview | None:
        """Заявка на проверке или опубликованная (выборочная проверка после публикации);
        None — нет такой, удалена или проверять нечего."""
        ...

    async def approve_job(self, job_id: UUID, *, version: int | None) -> None:
        """Проверка пройдена — в транзакции вызывающего: ждавшая проверки публикуется; другая
        версия (клиент успел поправить) или статус — ничего."""
        ...

    async def reject_job(self, job_id: UUID, *, reason_code: str) -> None:
        """Нарушение — в транзакции вызывающего: ждавшая проверки отклоняется (клиент
        исправит), опубликованная снимается."""
        ...

    async def job_brief(self, job_id: UUID) -> JobBrief | None:
        """Название, статус и срок заявки; None — нет такой или удалена."""
        ...

    async def responses_notice(self, job_id: UUID) -> ResponsesNotice | None:
        """Название, статус и непросмотренные отклики заявки; None — нет такой или удалена."""
        ...

    async def response_job(self, response_id: UUID) -> UUID | None:
        """Заявка отклика — куда вести исполнителя из уведомления о его отклике."""
        ...

    async def owner_responses(self, job_id: UUID, owner_id: UserId) -> list[OwnerResponseView]:
        """Отклики на свою заявку по порядку (S23); чужая или удалённая — JobNotFoundError
        (404 `job_not_found`)."""
        ...

    async def see_responses(self, job_id: UUID) -> None:
        """Владелец открыл отклики — в транзакции вызывающего: дальше «новые» — только те, что
        пройдут проверку позже. Версия заявки не меняется."""
        ...

    async def invite_notice(self, job_id: UUID, performer_id: UserId) -> InviteNotice | None:
        """Заявка, клиент и шаблоны приглашённого для `job.invited`; None — заявки нет или она
        удалена."""
        ...

    async def response_for_review(self, response_id: UUID) -> ResponseForReview | None:
        """Отклик, ждущий проверки; None — нет такого, удалён или проверять нечего."""
        ...

    async def approve_response(self, response_id: UUID, *, version: int | None) -> None:
        """Проверка пройдена — в транзакции вызывающего: клиент видит отклик; другая редакция
        (исполнитель успел поправить) или уже решено — ничего."""
        ...

    async def reject_response(self, response_id: UUID, *, reason_code: str) -> None:
        """Нарушение — в транзакции вызывающего: отклик скрыт, его место освобождается."""
        ...
