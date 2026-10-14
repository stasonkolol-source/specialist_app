"""Бот deals (DEVELOPMENT_PLAN 6.1b, 6.3b; ARCHITECTURE §11.3): кнопки под уведомлениями о сделке
(рисует notifications, данные — platform/telegram/callbacks.py).

- «Да, выполнено» под «Работа выполнена?» (`deal.completion_prompt`) — тот же CompleteDeal, что
  `POST /deals/{id}/complete` и S26: отметка стороны, вторая — завершает сделку. Повтор нажатия
  ничего не меняет, а у уже завершённой сделки — «Сделка завершена». По сделке открыт спор
  (6.1c) — отметки нет, «решение примет поддержка»: «Есть проблема» уже нажата.
- «Подтвердить» и «Отклонить» под «Договорились?» (`deal.proposed`) — те же ConfirmDeal и
  DeclineDeal, что S53. Предложение уже подтвердили, отклонили или оно истекло — «уже
  неактуально», ничего не меняется.

- «Ещё нет» под «Работа выполнена?» — SnoozeCompletion: вопрос придёт снова через сутки (не
  больше трёх раз; потом кнопки нет, а старая отвечает «переносить больше нельзя»).

Сообщение заменяется итогом без кнопок. Чужая сделка — «не найдена» (ErrorMiddleware).
"""

from typing import Final

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from dishka.integrations.aiogram import FromDishka, inject

from app.modules.deals.application.use_cases.complete_deal import (
    CompleteDeal,
    CompleteDealCommand,
)
from app.modules.deals.application.use_cases.confirm_deal import ConfirmDeal, ConfirmDealCommand
from app.modules.deals.application.use_cases.decline_deal import DeclineDeal, DeclineDealCommand
from app.modules.deals.application.use_cases.snooze_completion import (
    SnoozeCompletion,
    SnoozeCompletionCommand,
)
from app.modules.deals.domain.deal import DealStatus
from app.modules.deals.errors import DealNotActiveError
from app.platform.i18n.translator import Translator
from app.platform.kernel.ids import DealId
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Principal
from app.platform.telegram.callbacks import CallbackAction, parse_callback
from app.platform.telegram.texts import html_text, plain_text

CLOSED: Final = {
    DealStatus.COMPLETED.value: "bot.deals.completed",
    DealStatus.DISPUTED.value: "bot.deals.disputed",
}
"""Сделка уже не идёт: что ответить вместо действия; остальное — «Сделка отменена»."""


@inject
async def complete(
    callback: CallbackQuery,
    locale: Locale,
    translator: FromDishka[Translator],
    complete_deal: FromDishka[CompleteDeal],
    principal: Principal | None = None,
) -> None:
    data = parse_callback(callback.data)
    if principal is None or data is None:
        await callback.answer()
        return
    try:
        completed = await complete_deal(
            CompleteDealCommand(actor_id=principal.user_id, deal_id=DealId(data.id))
        )
    except DealNotActiveError as exc:
        status = exc.params.get("deal_status")
        if status == DealStatus.DISPUTED.value:
            await callback.answer()
            await _replace(callback, html_text(translator, "bot.deals.disputed", locale))
            return
        if status != DealStatus.COMPLETED.value:
            raise
        completed = True  # завершилась раньше: второй стороной или через 72 ч
    await callback.answer()
    key = "bot.deals.completed" if completed else "bot.deals.marked"
    await _replace(callback, html_text(translator, key, locale))


@inject
async def confirm(
    callback: CallbackQuery,
    locale: Locale,
    translator: FromDishka[Translator],
    confirm_deal: FromDishka[ConfirmDeal],
    principal: Principal | None = None,
) -> None:
    data = parse_callback(callback.data)
    if principal is None or data is None:
        await callback.answer()
        return
    key = "bot.deals.confirmed"
    try:
        await confirm_deal(ConfirmDealCommand(actor_id=principal.user_id, deal_id=DealId(data.id)))
    except DealNotActiveError as exc:
        if exc.params.get("deal_status") != DealStatus.AGREED.value:
            key = "bot.deals.proposal_closed"  # отклонили, истекло или своё предложение
    await callback.answer()
    await _replace(callback, html_text(translator, key, locale))


@inject
async def decline(
    callback: CallbackQuery,
    locale: Locale,
    translator: FromDishka[Translator],
    decline_deal: FromDishka[DeclineDeal],
    principal: Principal | None = None,
) -> None:
    data = parse_callback(callback.data)
    if principal is None or data is None:
        await callback.answer()
        return
    key = "bot.deals.declined"
    try:
        await decline_deal(DeclineDealCommand(actor_id=principal.user_id, deal_id=DealId(data.id)))
    except DealNotActiveError as exc:
        if exc.params.get("deal_status") != DealStatus.CANCELLED.value:
            key = "bot.deals.proposal_closed"  # уже подтвердили: отмена — только с причиной
    await callback.answer()
    await _replace(callback, html_text(translator, key, locale))


@inject
async def snooze(
    callback: CallbackQuery,
    locale: Locale,
    translator: FromDishka[Translator],
    snooze_completion: FromDishka[SnoozeCompletion],
    principal: Principal | None = None,
) -> None:
    """«Ещё нет»: спросим снова через сутки; переносов уже три — ответ всплывающим текстом,
    вопрос с «Да» и «Есть проблема» остаётся."""
    data = parse_callback(callback.data)
    if principal is None or data is None:
        await callback.answer()
        return
    try:
        snoozed = await snooze_completion(
            SnoozeCompletionCommand(actor_id=principal.user_id, deal_id=DealId(data.id))
        )
    except DealNotActiveError as exc:
        await callback.answer()
        await _replace(callback, _closed(translator, locale, exc.params.get("deal_status")))
        return
    if not snoozed:
        limit = plain_text(translator, "bot.deals.snooze_limit", locale)
        await callback.answer(limit, show_alert=True)
        return
    await callback.answer()
    await _replace(callback, html_text(translator, "bot.deals.snoozed", locale))


def _closed(translator: Translator, locale: Locale, status: object) -> str:
    """Сделка уже не идёт: завершена, под спором или отменена."""
    key = CLOSED.get(str(status), "bot.deals.cancelled")
    return html_text(translator, key, locale)


async def _replace(
    callback: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None
) -> None:
    """Заменить вопрос итогом (без кнопок или с кнопками `markup`); старое (недоступное боту)
    сообщение — оставить."""
    if not isinstance(callback.message, Message):
        return
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:  # двойное нажатие: тот же текст Telegram отвергает
        if "message is not modified" not in exc.message:
            raise


def create_router() -> Router:
    """Новый роутер на каждый вызов: роутер aiogram подключается только к одному диспетчеру."""
    router = Router(name="deals")
    for action, handler in (
        (CallbackAction.DEAL_COMPLETE, complete),
        (CallbackAction.DEAL_CONFIRM, confirm),
        (CallbackAction.DEAL_DECLINE, decline),
        (CallbackAction.DEAL_SNOOZE, snooze),
    ):
        router.callback_query.register(handler, F.data.startswith(f"{action}:"))
    return router
