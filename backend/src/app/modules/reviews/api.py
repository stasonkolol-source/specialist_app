"""Контракт модуля reviews для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из reviews только этот файл.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Protocol
from uuid import UUID

from app.platform.kernel.ids import DealId, UserId
from app.platform.kernel.pagination import Page, PageRequest

NEW_UNTIL_REVIEWS: Final = 3
"""«Новый специалист» — пока отзывов по сделкам меньше трёх (ARCHITECTURE §9.4)."""
DEAL: Final = "deal"
PRE_PLATFORM: Final = "pre_platform"
"""Вид отзыва (ReviewKind): по сделке или «до платформы» по приглашению (7.6а) — вкладки S11."""
NO_REVIEWS_LOWER_BOUND: Final = 2.05
"""Нижняя граница рейтинга профиля без отзывов (только априорное распределение): ранжирование
ставит такой профиль выше профиля с одной «единицей» и ниже профиля с одной «пятёркой».
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class RatingSummary:
    """Рейтинг профиля по отзывам сделок; «до платформы» в него не входят (ADR-0016)."""

    count: int
    average: float
    """Для показа и фильтра «рейтинг от» — байесовское среднее: «4,9»."""
    lower_bound: float = NO_REVIEWS_LOWER_BOUND
    """Нижняя граница доверительного интервала — ранжирование в поиске."""
    distribution: tuple[int, ...]
    """Сколько оценок в 1, 2, 3, 4 и 5 звёзд — гистограмма S11."""
    criteria: Mapping[str, float] = field(default_factory=dict)
    """Средние по критериям: quality, punctuality, communication, price."""
    last_published_at: datetime | None = None

    @property
    def is_new(self) -> bool:
        return self.count < NEW_UNTIL_REVIEWS


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplyView:
    """Публичный ответ исполнителя на отзыв (прошёл проверку)."""

    body: str
    at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class PublicReview:
    """Опубликованный отзыв на карточке специалиста (S08, S11)."""

    id: UUID
    kind: str
    """ReviewKind: `deal` или `pre_platform` (7.6)."""
    author_id: UserId
    subject_profile_id: UUID | None
    rating: int
    criteria: Mapping[str, int]
    body: str | None
    category_id: int | None
    published_at: datetime
    reply: ReplyView | None
    work_title: str | None = None
    """«Что делал мастер» — у отзыва до платформы вместо услуги сделки."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MyReview:
    """Свой отзыв по сделке — карточка сделки S26 и S27: что уже оставлено и в каком статусе."""

    id: UUID
    status: str
    """ReviewStatus: `under_review`, `published`, `removed`."""
    rating: int


@dataclass(frozen=True, slots=True, kw_only=True)
class DealRef:
    """Сделка для состояния отзыва (фасад deals): кто клиент, статус, когда завершена."""

    id: DealId
    client_id: UserId
    status: str
    completed_at: datetime | None


@dataclass(frozen=True, slots=True, kw_only=True)
class DealReviewState:
    """Отзыв по сделке глазами стороны (S26, S27): свой уже оставлен или до когда можно."""

    mine: MyReview | None
    open_until: datetime | None
    """Клиент может оставить отзыв до этого времени (14 дней после завершения); None — нельзя
    или уже оставлен."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewForCheck:
    """Что проверять модерации (адаптеры целей `review` и `review_reply`): отзыв и ответ не
    редактируются, поэтому версии у проверки нет."""

    author_id: UserId
    text: str
    always_review: bool = False
    """Отзыв до платформы проверяет человек всегда (ADR-0016: «модерация обязательна»)."""
    rating: int | None = None
    """Оценка отзыва (у ответа — None): в карточку кейса в чате модераторов (2.5b)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class InviteRef:
    """Действующая ссылка-приглашение на «отзыв до платформы» (S56): чей профиль."""

    profile_id: UUID
    expires_at: datetime


class ReviewsApi(Protocol):
    async def summaries(self, profile_ids: Collection[UUID]) -> dict[UUID, RatingSummary]:
        """Рейтинг профилей; профиль без отзывов по сделкам в ответ не попадает."""
        ...

    async def reviews_of(
        self, profile_id: UUID, page: PageRequest, *, kind: str = DEAL
    ) -> Page[PublicReview]:
        """Опубликованные отзывы профиля этого вида, новые первыми (S11; первый по сделке — на
        S08)."""
        ...

    async def review_count(self, profile_id: UUID, *, kind: str) -> int:
        """Сколько опубликованных отзывов этого вида: «До платформы · 2» на S11."""
        ...

    async def open_invite(self, token: UUID) -> InviteRef | None:
        """Ссылка-приглашение, по которой ещё можно оставить отзыв; отозванная, истёкшая,
        использованная и несуществующая — None (одинаково)."""
        ...

    async def published_review(self, review_id: UUID) -> PublicReview | None:
        """Опубликованный отзыв (уведомление `review.published`); снят или стёрт — None."""
        ...

    async def review_state(
        self,
        deal_id: DealId,
        viewer_id: UserId,
        *,
        client_id: UserId,
        status: str,
        completed_at: datetime | None,
    ) -> DealReviewState:
        """Отзыв стороны по сделке: свой (не стёртый) и срок, до которого клиент может его
        оставить (по сделке `completed`, 14 дней после завершения)."""
        ...

    async def review_states(
        self, viewer_id: UserId, deals: Collection[DealRef]
    ) -> dict[DealId, DealReviewState]:
        """То же пачкой — список сделок S28."""
        ...

    async def review_for_check(self, review_id: UUID) -> ReviewForCheck | None:
        """Текст отзыва, который ждёт проверки; None — отзыва нет или он уже не ждёт."""
        ...

    async def approve_review(self, review_id: UUID) -> None:
        """Проверка пройдена: отзыв опубликован (в транзакции вызывающего)."""
        ...

    async def reject_review(self, review_id: UUID, *, reason_code: str) -> None:
        """Нарушение: отзыв снят (в транзакции вызывающего)."""
        ...

    async def reply_for_check(self, review_id: UUID) -> ReviewForCheck | None:
        """Ответ исполнителя, который ждёт проверки; None — нет такого."""
        ...

    async def approve_reply(self, review_id: UUID) -> None:
        """Ответ прошёл проверку и виден (в транзакции вызывающего)."""
        ...

    async def reject_reply(self, review_id: UUID, *, reason_code: str) -> None:
        """Нарушение в ответе: ответ скрыт, отзыв остаётся (в транзакции вызывающего)."""
        ...
