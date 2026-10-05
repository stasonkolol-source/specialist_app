"""Карточка нового кейса в чате модераторов (DEVELOPMENT_PLAN 2.5b; подписчик CaseOpened).

Кейс читается заново: к моменту задачи его могли уже решить (`cli`, автопроверка) — тогда
карточка не нужна. Чат не задан (K29 ещё нет) — ничего: кейс виден в `cli moderation-queue`.
Контекст карточки (кто, что и почему — application/case_card.py) собирается одним вызовом
CaseContextQuery через фасады модулей-владельцев.

Id сообщения карточки записывается в кейс. Кейс, открытый вместо устаревшего (объект изменили
после карточки, ADV-11), сначала гасит кнопки прежней карточки: «Версия изменилась — смотрите
новую карточку». Не успели записать id прежней — её кнопки погасит бот при нажатии.
"""

from dataclasses import dataclass

from app.modules.moderation.application.ports import (
    CaseContextQuery,
    CaseRepository,
    ModeratorsChat,
)
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import CaseId


@dataclass(frozen=True, slots=True, kw_only=True)
class PostCaseCardCommand:
    case_id: CaseId


class PostCaseCard:
    def __init__(
        self,
        uow: UnitOfWork,
        cases: CaseRepository,
        contexts: CaseContextQuery,
        chat: ModeratorsChat,
    ) -> None:
        self._uow, self._cases, self._contexts, self._chat = uow, cases, contexts, chat

    async def __call__(self, cmd: PostCaseCardCommand) -> bool:
        """True — карточка отправлена."""
        if not self._chat.enabled:
            return False
        case = await self._cases.get(cmd.case_id)
        if case is None or not case.is_open:
            return False
        if case.supersedes is not None:
            previous = await self._cases.get(case.supersedes)
            if previous is not None and previous.card_message_id is not None:
                await self._chat.retire(previous)
        message_id = await self._chat.post(case, await self._contexts.context(case))
        if message_id is not None:
            async with self._uow:
                posted = await self._cases.get_for_update(case.id)
                posted.card_message_id = message_id
                await self._cases.save(posted)
        return True
