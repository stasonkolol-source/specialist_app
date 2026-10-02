"""Бот deals (DEVELOPMENT_PLAN 6.1b; ARCHITECTURE §11.3): «Да, выполнено» под «Работа выполнена?»
(`deal.completion_prompt`, кнопку рисует notifications, данные — platform/telegram/callbacks.py).

Нажатие — тот же CompleteDeal, что `POST /deals/{id}/complete` и S26: отметка стороны, вторая —
завершает сделку. Сообщение заменяется итогом без кнопок. Повтор нажатия ничего не меняет, а у
уже завершённой сделки — «Сделка завершена». Чужая сделка — «не найдена» (ErrorMiddleware).
"""

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from dishka.integrations.aiogram import FromDishka, inject

from app.modules.deals.application.use_cases.complete_deal import (
    CompleteDeal,
    CompleteDealCommand,
)
from app.modules.deals.domain.deal import DealStatus
from app.modules.deals.errors import DealNotActiveError
from app.platform.i18n.translator import Translator
from app.platform.kernel.ids import DealId
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Principal
from app.platform.telegram.callbacks import CallbackAction, parse_callback
from app.platform.telegram.texts import html_text


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
        if exc.params.get("deal_status") != DealStatus.COMPLETED.value:
            raise
        completed = True  # завершилась раньше: второй стороной или через 72 ч
    await callback.answer()
    key = "bot.deals.completed" if completed else "bot.deals.marked"
    await _replace(callback, html_text(translator, key, locale))


async def _replace(callback: CallbackQuery, text: str) -> None:
    """Заменить вопрос итогом без кнопок; старое (недоступное боту) сообщение — оставить."""
    if not isinstance(callback.message, Message):
        return
    try:
        await callback.message.edit_text(text, reply_markup=None)
    except TelegramBadRequest as exc:  # двойное нажатие: тот же текст Telegram отвергает
        if "message is not modified" not in exc.message:
            raise


def create_router() -> Router:
    """Новый роутер на каждый вызов: роутер aiogram подключается только к одному диспетчеру."""
    router = Router(name="deals")
    router.callback_query.register(complete, F.data.startswith(f"{CallbackAction.DEAL_COMPLETE}:"))
    return router
