"""«Пожаловаться» в один тап из бота (пути «Есть проблема», 2026-10-14): кнопка под «Вы выбрали …»
(`response.chosen`) и под «Есть проблема» — «Просит предоплату → пожаловаться» (данные —
platform/telegram/callbacks.py, `DEAL_REPORT`). Жалоба `fraud` на вторую сторону сделки — тем же
CreateReport, что шторка S46, без шторки: P1, модератор проверит аккаунт. Повтор, пока жалоба
открыта, — та же жалоба. Ответ — всплывающим текстом, кнопка «Пожаловаться» под сообщением
пропадает, остальные остаются. Чужая сделка — «не найдена», лимит жалоб — текстом ошибки
(ErrorMiddleware)."""

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from dishka.integrations.aiogram import FromDishka, inject

from app.modules.deals.api import DealNotFoundError, DealsApi
from app.modules.moderation.application.use_cases.create_report import (
    CreateReport,
    CreateReportCommand,
)
from app.modules.moderation.domain.cases import EntityType
from app.modules.moderation.domain.reports import ReportReason
from app.platform.i18n.translator import Translator
from app.platform.kernel.ids import DealId
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Principal
from app.platform.telegram.callbacks import CallbackAction, parse_callback
from app.platform.telegram.texts import plain_text


@inject
async def report_deal(
    callback: CallbackQuery,
    locale: Locale,
    translator: FromDishka[Translator],
    deals: FromDishka[DealsApi],
    create_report: FromDishka[CreateReport],
    principal: Principal | None = None,
) -> None:
    data = parse_callback(callback.data)
    if principal is None or data is None:
        await callback.answer()
        return
    deal_id = DealId(data.id)
    deal = await deals.deal_brief(deal_id)
    if deal is None or principal.user_id not in (deal.client_id, deal.performer_id):
        raise DealNotFoundError(deal_id=deal_id)
    other = deal.performer_id if principal.user_id == deal.client_id else deal.client_id
    await create_report(
        CreateReportCommand(
            reporter_id=principal.user_id,
            target_type=EntityType.USER,
            target_id=other,
            reason=ReportReason.FRAUD,
        )
    )
    await callback.answer(plain_text(translator, "bot.deals.reported", locale), show_alert=True)
    await _drop_report_button(callback)


async def _drop_report_button(callback: CallbackQuery) -> None:
    """Жалоба ушла — «Пожаловаться» больше не нужна; «Открыть сделку» и пути спора остаются."""
    message = callback.message
    if not isinstance(message, Message) or message.reply_markup is None:
        return
    prefix = f"{CallbackAction.DEAL_REPORT}:"
    rows = [
        kept
        for row in message.reply_markup.inline_keyboard
        if (kept := [b for b in row if not (b.callback_data or "").startswith(prefix)])
    ]
    try:
        await message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    except TelegramBadRequest as exc:  # двойное нажатие: разметка уже та же
        if "message is not modified" not in exc.message:
            raise
