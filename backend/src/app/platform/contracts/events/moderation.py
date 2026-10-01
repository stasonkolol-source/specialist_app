"""События модуля moderation (ADR-0020 §2). Публикует модуль moderation (шаг 2.5a).

`ModerationDecision` — часть published language: подписчики (уведомления) решают по нему,
писать ли автору.
"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import CaseId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ModerationRequested(DomainEvent):
    """Объект ждёт проверки (ARCHITECTURE §14.1): новый или изменённый профиль, заявка,
    отклик, сообщение, отзыв.

    Публикует модуль-владелец в транзакции, где объект стал «на проверке»; подписчик —
    `moderation.auto_check`. Текст и файлы конвейер берёт у модуля через адаптер цели
    (moderation/infrastructure/targets): в событии только ссылка. `entity_type` — как
    `moderation.cases.entity_type`; `edit` — правка уже опубликованного.
    """

    event_type = "moderation.ModerationRequested"
    entity_type: str
    entity_id: UUID
    author_id: UserId
    edit: bool = False


class ModerationDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True, kw_only=True)
class ModerationDecisionMade(DomainEvent):
    """Кейс модерации решён: модератором или автопроверкой (moderation.cases).

    `author_id` — чей контент; при отказе ему уходит уведомление `moderation.decision` —
    statement of reasons (ADR-0016 §4): что сделано, какое правило, автоматически ли.
    `entity_type` — что проверяли: `job`, `profile`, `response`, `review`, `message`,
    `media`, `user` (как `moderation.cases.entity_type`). `decision_code` — машинный код
    причины: метки ADR-0016 (`contact_leak`, `spam_ad`, `prepayment_scam`, …) или `other`.
    `automated` — решила автопроверка, а не человек. `sanction` — ступень лестницы санкций
    (`warning`, `strike_1`, `strike_2`, `ban`, `suspension`), если назначена: о санкции,
    которая что-то запрещает, отдельно сообщает `UserRestricted`. Поля `automated` и
    `sanction` добавлены аддитивно (2.5a).
    """

    event_type = "moderation.ModerationDecisionMade"
    case_id: CaseId
    author_id: UserId
    entity_type: str
    entity_id: UUID
    decision: ModerationDecision
    decision_code: str | None = None
    automated: bool = False
    sanction: str | None = None
