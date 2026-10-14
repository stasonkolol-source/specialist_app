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
- «Есть проблема» под «Работа выполнена?» — три пути вместо спора на любую беду (кнопками под тем
  же сообщением). Клиенту: «Не пришёл / нет связи → отменить» — CancelDeal с причиной
  `no_contact` (заявка снова открыта — «Выбрать из откликов»; жалобу `no_show` на исполнителя
  подаёт модерация по DealCancelled), «Просит предоплату → пожаловаться» — жалоба `fraud` в один
  тап (бот moderation), «Сделал плохо, ущерб → спор» — S52. Исполнителю: «Клиент не на связи →
  отменить» и «Другая проблема → спор». Работу уже отметили — отменить нельзя (MU-8): «не
  пришёл» ведёт в спор. Ниже остаётся «Всё хорошо, работа выполнена», если передумали.

Сообщение заменяется итогом без кнопок (кроме «Выбрать из откликов» и спора). Чужая сделка — «не
найдена» (ErrorMiddleware).
"""

from typing import Final

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from dishka.integrations.aiogram import FromDishka, inject

from app.modules.deals.application.dto import DealView
from app.modules.deals.application.use_cases.cancel_deal import CancelDeal, CancelDealCommand
from app.modules.deals.application.use_cases.complete_deal import (
    CompleteDeal,
    CompleteDealCommand,
)
from app.modules.deals.application.use_cases.confirm_deal import ConfirmDeal, ConfirmDealCommand
from app.modules.deals.application.use_cases.decline_deal import DeclineDeal, DeclineDealCommand
from app.modules.deals.application.use_cases.show_deal import ShowDeal, ShowDealCommand
from app.modules.deals.application.use_cases.snooze_completion import (
    SnoozeCompletion,
    SnoozeCompletionCommand,
)
from app.modules.deals.domain.deal import DealCancelReason, DealRole, DealStatus
from app.modules.deals.errors import DealMarkedDoneError, DealNotActiveError
from app.platform.i18n.translator import Translator
from app.platform.kernel.ids import DealId
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Principal
from app.platform.settings import TelegramSettings
from app.platform.telegram.buttons import mini_app_url
from app.platform.telegram.callbacks import (
    CallbackAction,
    CallbackData,
    encode_callback,
    parse_callback,
)
from app.platform.telegram.deeplinks import LinkType, StartLink, encode_start_param
from app.platform.telegram.texts import html_text, plain_text

CANCEL: Final = "cancel"
"""Аргумент «Есть проблема»: «Не пришёл / нет связи» — отменить сделку."""

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


@inject
async def problem(
    callback: CallbackQuery,
    locale: Locale,
    translator: FromDishka[Translator],
    show_deal: FromDishka[ShowDeal],
    cancel_deal: FromDishka[CancelDeal],
    telegram: FromDishka[TelegramSettings],
    principal: Principal | None = None,
) -> None:
    """«Есть проблема»: без аргумента — что случилось, кнопками; `cancel` — «Не пришёл / нет
    связи»: сделка отменяется с причиной `no_contact`, клиенту — «Выбрать из откликов»."""
    data = parse_callback(callback.data)
    if principal is None or data is None:
        await callback.answer()
        return
    deal = await show_deal(ShowDealCommand(actor_id=principal.user_id, deal_id=DealId(data.id)))
    base = telegram.mini_app_url
    if deal.status is not DealStatus.AGREED:
        await callback.answer()
        await _replace(callback, _closed(translator, locale, deal.status.value))
        return
    if data.arg is None:
        await callback.answer()
        await _replace(
            callback,
            html_text(translator, "bot.deals.problem.question", locale, title=deal.title),
            _problems(deal, principal, translator, locale, base),
        )
        return
    if data.arg != CANCEL:
        await callback.answer()
        return
    try:
        await cancel_deal(
            CancelDealCommand(
                actor_id=principal.user_id, deal_id=deal.id, reason=DealCancelReason.NO_CONTACT
            )
        )
    except DealMarkedDoneError:  # вторая сторона успела отметить «Работа выполнена» (MU-8)
        await callback.answer()
        rows = [_dispute_button(deal, "bot.deals.problem.dispute", translator, locale, base)]
        await _replace(
            callback, html_text(translator, "bot.deals.problem.marked", locale), _markup(rows)
        )
        return
    except DealNotActiveError as exc:
        await callback.answer()
        await _replace(callback, _closed(translator, locale, exc.params.get("deal_status")))
        return
    await callback.answer()
    if deal.role_of(principal.user_id) is DealRole.CLIENT and deal.job_id is not None:
        rows = []
        if base:
            link = encode_start_param(StartLink(type=LinkType.JOB, id=deal.job_id))
            label = plain_text(translator, "bot.deals.problem.responses", locale)
            rows.append([InlineKeyboardButton(text=label, web_app=_app(base, link))])
        text = html_text(translator, "bot.deals.problem.reopened", locale, title=deal.title)
        await _replace(callback, text, _markup(rows))
        return
    await _replace(
        callback, html_text(translator, "bot.deals.problem.cancelled", locale, title=deal.title)
    )


def _problems(
    deal: DealView, principal: Principal, translator: Translator, locale: Locale, base: str | None
) -> InlineKeyboardMarkup | None:
    """Пути «что-то пошло не так»: клиенту — три, исполнителю — два; работу уже отметили —
    «не пришёл» ведёт в спор (отменить нельзя, MU-8). Внизу — «Всё хорошо», если передумали."""
    client = deal.role_of(principal.user_id) is DealRole.CLIENT
    marked = deal.client_confirmed_at is not None or deal.performer_confirmed_at is not None
    role = "client" if client else "performer"
    rows: list[list[InlineKeyboardButton]] = []
    if marked:
        key = f"bot.deals.problem.no_show_{role}_dispute"
        rows.append(_dispute_button(deal, key, translator, locale, base))
    else:
        rows.append(
            [_callback(translator, locale, f"bot.deals.problem.no_show_{role}", deal, CANCEL)]
        )
    if client:
        rows.append(
            [
                InlineKeyboardButton(
                    text=plain_text(translator, "bot.deals.problem.prepayment", locale),
                    callback_data=encode_callback(
                        CallbackData(CallbackAction.DEAL_REPORT, deal.id)
                    ),
                )
            ]
        )
    rows.append(_dispute_button(deal, f"bot.deals.problem.other_{role}", translator, locale, base))
    mine = deal.client_confirmed_at if client else deal.performer_confirmed_at
    if mine is None:
        rows.append(
            [
                InlineKeyboardButton(
                    text=plain_text(translator, "bot.deals.problem.fine", locale),
                    callback_data=encode_callback(
                        CallbackData(CallbackAction.DEAL_COMPLETE, deal.id)
                    ),
                )
            ]
        )
    return _markup(rows)


def _callback(
    translator: Translator, locale: Locale, key: str, deal: DealView, arg: str
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=plain_text(translator, key, locale),
        callback_data=encode_callback(CallbackData(CallbackAction.DEAL_PROBLEM, deal.id, arg)),
    )


def _dispute_button(
    deal: DealView, key: str, translator: Translator, locale: Locale, base: str | None
) -> list[InlineKeyboardButton]:
    """Спор S52 сразу, без S26 (`p_`); без адреса Mini App — без кнопки."""
    if not base:
        return []
    link = encode_start_param(StartLink(type=LinkType.DISPUTE, id=deal.id))
    return [
        InlineKeyboardButton(text=plain_text(translator, key, locale), web_app=_app(base, link))
    ]


def _app(base: str, link: str) -> WebAppInfo:
    return WebAppInfo(url=mini_app_url(base, link))


def _markup(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup | None:
    kept = [row for row in rows if row]
    return InlineKeyboardMarkup(inline_keyboard=kept) if kept else None


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
        (CallbackAction.DEAL_PROBLEM, problem),
    ):
        router.callback_query.register(handler, F.data.startswith(f"{action}:"))
    return router
