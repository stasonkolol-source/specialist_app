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


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportCreated(DomainEvent):
    """Пользователь пожаловался (шторка S46, DEVELOPMENT_PLAN 4.7): жалоба стала поводом кейса.

    `target_type` — на что: `profile`, `job`, `review`, `message`, `user` (как
    `moderation.reports.target_type`); `reason` — причина из списка типа (`fraud`, `offensive`,
    …); `queue` — очередь кейса (`safety` — P0, `fraud` — P1). Подписчики: аналитика
    `report_created`; карточка в чате модераторов — с 2.5b. Текста жалобы в событии нет.
    """

    event_type = "moderation.ReportCreated"
    report_id: UUID
    reporter_id: UserId
    target_type: str
    target_id: UUID
    reason: str
    case_id: CaseId
    queue: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CaseOpened(DomainEvent):
    """Открыт кейс модерации (DEVELOPMENT_PLAN 2.5b): автопроверка, жалоба, спор или апелляция.

    Подписчик — `moderation.post_case_card`: карточка кейса в чате модераторов. Второй повод
    по объекту дописывается в открытый кейс и события не публикует. `queue` — `safety`,
    `fraud`, `premod`, `appeals`; `entity_type` — как `moderation.cases.entity_type`;
    `trigger` — первый повод (`report`, `dispute`, `appeal`, …).
    """

    event_type = "moderation.CaseOpened"
    case_id: CaseId
    queue: str
    entity_type: str
    trigger: str


@dataclass(frozen=True, slots=True, kw_only=True)
class AppealDecided(DomainEvent):
    """Модератор решил апелляцию (POST /appeals, DEVELOPMENT_PLAN 2.5b; ARCHITECTURE §14.4).

    `granted` — апелляция удовлетворена: санкция по обжалованному решению снята; иначе решение
    остаётся в силе, `decision_code` — почему. Подписчик — уведомление `moderation.decision`
    автору апелляции (statement of reasons).
    """

    event_type = "moderation.AppealDecided"
    case_id: CaseId
    appeal_of: CaseId
    user_id: UserId
    granted: bool
    decision_code: str | None = None
