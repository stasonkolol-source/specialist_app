"""Карточка нового кейса в чате модераторов (DEVELOPMENT_PLAN 2.5b; подписчик CaseOpened).

Кейс читается заново: к моменту задачи его могли уже решить (`cli`, автопроверка) — тогда
карточка не нужна. Чат не задан (K29 ещё нет) — ничего: кейс виден в `cli moderation-queue`.
Контекст карточки (кто, что и почему — application/case_card.py) собирается одним вызовом
CaseContextQuery через фасады модулей-владельцев.
"""

from dataclasses import dataclass

from app.modules.moderation.application.ports import (
    CaseContextQuery,
    CaseRepository,
    ModeratorsChat,
)
from app.platform.kernel.ids import CaseId


@dataclass(frozen=True, slots=True, kw_only=True)
class PostCaseCardCommand:
    case_id: CaseId


class PostCaseCard:
    def __init__(
        self, cases: CaseRepository, contexts: CaseContextQuery, chat: ModeratorsChat
    ) -> None:
        self._cases, self._contexts, self._chat = cases, contexts, chat

    async def __call__(self, cmd: PostCaseCardCommand) -> bool:
        """True — карточка отправлена."""
        if not self._chat.enabled:
            return False
        case = await self._cases.get(cmd.case_id)
        if case is None or not case.is_open:
            return False
        await self._chat.post(case, await self._contexts.context(case))
        return True
