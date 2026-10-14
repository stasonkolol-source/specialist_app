"""«Ещё нет» под «Работа выполнена?» (кнопка бота, `deal.completion_prompt`): вопрос переносится на
сутки — `deals.completion_prompts` задаст его снова тем, кто ещё не отметил. Не больше трёх раз на
сделку: потом под вопросом только «Да» и «Есть проблема». Сделка не идёт — DealNotActiveError."""

from dataclasses import dataclass

from app.modules.deals.application.ports import DealRepository
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import DealId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class SnoozeCompletionCommand:
    actor_id: UserId
    deal_id: DealId


class SnoozeCompletion:
    def __init__(self, uow: UnitOfWork, deals: DealRepository, clock: Clock) -> None:
        self._uow, self._deals, self._clock = uow, deals, clock

    async def __call__(self, cmd: SnoozeCompletionCommand) -> bool:
        """True — спросим снова через сутки; False — переносов уже три."""
        async with self._uow:
            deal = await self._deals.get_for_update(cmd.deal_id)
            snoozed = deal.snooze_completion(actor_id=cmd.actor_id, now=self._clock.now())
            if snoozed:
                await self._deals.save(deal)
        return snoozed
