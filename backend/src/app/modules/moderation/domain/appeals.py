"""Апелляция (DEVELOPMENT_PLAN 2.5b; ARCHITECTURE §14.4, ADR-0016 §4): решение модерации
пересматривает человек.

Обжаловать можно своё решение с нарушением (`rejected`) — отказ в публикации, санкцию,
решение по спору с санкцией — в течение шести месяцев после решения (столько отклонённый
контент хранится скрытым). Апелляция на решение одна: её итог окончательный; повтор отдаёт
ту же апелляцию («уже обжаловано»). Апелляцию на апелляцию не подают.
"""

from datetime import datetime, timedelta
from typing import Final

from app.modules.moderation.domain.cases import Case, CaseStatus
from app.modules.moderation.errors import AppealTargetNotFoundError, AppealWindowClosedError
from app.platform.kernel.ids import UserId

APPEAL_WINDOW: Final = timedelta(days=183)
"""Шесть месяцев: окно апелляции и срок хранения отклонённого контента (§7.10)."""


def check_appealable(decision: Case, user_id: UserId, now: datetime) -> None:
    """Можно ли обжаловать решение: своё, с нарушением, не апелляция, окно не закрыто."""
    if (
        decision.subject_id != user_id
        or decision.status is not CaseStatus.REJECTED
        or decision.is_appeal
        or decision.decided_at is None
    ):
        raise AppealTargetNotFoundError
    if now - decision.decided_at > APPEAL_WINDOW:
        raise AppealWindowClosedError
