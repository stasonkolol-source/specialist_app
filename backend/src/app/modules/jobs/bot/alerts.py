"""Подписки на заявки в боте (DEVELOPMENT_PLAN 5.7, ARCHITECTURE §11.3): кнопки карточки B1 и
команды `/feed`, `/alerts`. Карточку рисует notifications, данные кнопок — общий кодек
platform/telegram/callbacks.py; нажатия — те же use cases, что Mini App.

- «Откликнуться шаблоном «…»» — handlers.respond (тот же Respond, что S16, как у приглашения).
- «Не подходит» — тот же HideJob, что S15: заявка пропадает из ленты, у карточки остаётся только
  «Открыть заявку».
- «Пауза подписки» — эта подписка молчит неделю; кнопка становится «Снять паузу».
- `/alerts` — подписки строками («сразу», «раз в день», «на паузе до …», «выключена», сколько
  заявок за неделю), «Пауза на сегодня», «Пауза на неделю» или «Снять паузу» для всех и «Настроить
  подписки» (S18, `m_alerts`).
- `/feed` — последние заявки по подпискам (лента `feed=alerts` без фото) кнопками на каждую
  (S15) и «Открыть ленту» (S13 «по моим подпискам», `m_feed`).
Без аккаунта — «Сначала нажмите /start».
"""

from datetime import datetime
from typing import Final

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dishka.integrations.aiogram import FromDishka, inject

from app.modules.catalog.api import CatalogApi
from app.modules.identity.api import IdentityApi
from app.modules.jobs.application.alerts import AlertItem
from app.modules.jobs.application.blocks import without_blocked
from app.modules.jobs.application.feed import FeedFilters, FeedItem
from app.modules.jobs.application.ports import JobQueries
from app.modules.jobs.application.use_cases.hide_job import HideJob, HideJobCommand
from app.modules.jobs.application.use_cases.list_alerts import ListAlerts, ListAlertsCommand
from app.modules.jobs.application.use_cases.pause_alerts import PauseAlerts, PauseAlertsCommand
from app.modules.jobs.bot.keyboards import app_keyboard, web_app_button
from app.modules.jobs.domain.alert import AlertId, JobAlert, PauseSpan
from app.modules.jobs.domain.job import BudgetType, JobId
from app.platform.i18n.dates import long_datetime
from app.platform.i18n.translator import Translator
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import CategoryId
from app.platform.kernel.localized import Locale
from app.platform.kernel.pagination import PageRequest
from app.platform.kernel.principal import Principal
from app.platform.settings import TelegramSettings
from app.platform.telegram.callbacks import (
    CallbackAction,
    CallbackData,
    encode_callback,
    parse_callback,
)
from app.platform.telegram.deeplinks import LinkSection, LinkType, StartLink, encode_start_param
from app.platform.telegram.texts import html_text, plain_text

ALERTS_LINK: Final = encode_start_param(StartLink(type=LinkType.MINE, section=LinkSection.ALERTS))
FEED_LINK: Final = encode_start_param(StartLink(type=LinkType.MINE, section=LinkSection.FEED))
FEED_SHOWN: Final = 5
"""Заявок в ответе `/feed`: остальные — в ленте Mini App."""
TITLE_CHARS: Final = 40
OFF: Final = "off"
"""Аргумент кнопки `/alerts`: снять паузу со всех подписок."""


@inject
async def hide(
    callback: CallbackQuery,
    locale: Locale,
    translator: FromDishka[Translator],
    hide_job: FromDishka[HideJob],
    principal: Principal | None = None,
) -> None:
    data = parse_callback(callback.data)
    if principal is None or data is None:
        await callback.answer()
        return
    await hide_job(HideJobCommand(actor_id=principal.user_id, job_id=JobId(data.id)))
    await callback.answer(plain_text(translator, "bot.alerts.hidden", locale))
    await _keep_app_buttons(callback)


@inject
async def pause(
    callback: CallbackQuery,
    locale: Locale,
    translator: FromDishka[Translator],
    pause_alerts: FromDishka[PauseAlerts],
    catalog: FromDishka[CatalogApi],
    principal: Principal | None = None,
) -> None:
    """«Пауза подписки» (B1) — на неделю; «Снять паузу» — сразу. Кнопка меняется на обратную."""
    data = parse_callback(callback.data)
    if principal is None or data is None:
        await callback.answer()
        return
    resume = data.action is CallbackAction.ALERT_RESUME
    changed = await pause_alerts(
        PauseAlertsCommand(
            actor_id=principal.user_id,
            span=None if resume else PauseSpan.WEEK,
            alert_id=AlertId(data.id),
        )
    )
    if not changed:  # подписку выключили на S18: пауза ей не нужна
        await callback.answer(plain_text(translator, "bot.alerts.inactive", locale))
        return
    alert = changed[0]
    name = await _alert_name(catalog, alert, locale, translator)
    if alert.paused_until is None:
        text = plain_text(translator, "bot.alerts.resumed_one", locale, alert=name)
    else:
        until = long_datetime(alert.paused_until, locale)
        text = plain_text(translator, "bot.alerts.paused_one", locale, alert=name, until=until)
    await callback.answer(text)
    await _swap_pause_button(callback, alert, resume=resume, translator=translator, locale=locale)


@inject
async def my_alerts(
    message: Message,
    locale: Locale,
    translator: FromDishka[Translator],
    listing: FromDishka[ListAlerts],
    catalog: FromDishka[CatalogApi],
    clock: FromDishka[Clock],
    telegram: FromDishka[TelegramSettings],
    principal: Principal | None = None,
) -> None:
    if principal is None:  # чат есть, а аккаунта нет — сначала /start
        await message.answer(html_text(translator, "bot.language.need_start", locale))
        return
    items = await listing(ListAlertsCommand(actor_id=principal.user_id))
    text, markup = await _alerts_view(
        items, principal, catalog, clock.now(), translator, telegram, locale
    )
    await message.answer(text, reply_markup=markup)


@inject
async def pause_all(
    callback: CallbackQuery,
    locale: Locale,
    translator: FromDishka[Translator],
    pause_alerts: FromDishka[PauseAlerts],
    listing: FromDishka[ListAlerts],
    catalog: FromDishka[CatalogApi],
    clock: FromDishka[Clock],
    telegram: FromDishka[TelegramSettings],
    principal: Principal | None = None,
) -> None:
    """Кнопки `/alerts`: пауза всех включённых на сегодня или неделю, «Снять паузу»; сообщение
    перерисовывается с новым состоянием."""
    data = parse_callback(callback.data)
    if principal is None or data is None or data.id != principal.user_id:
        await callback.answer()
        return
    span = None if data.arg == OFF else next((s for s in PauseSpan if s.value == data.arg), None)
    if span is None and data.arg != OFF:
        await callback.answer()
        return
    await pause_alerts(PauseAlertsCommand(actor_id=principal.user_id, span=span))
    key = "bot.alerts.resumed" if span is None else f"bot.alerts.paused_{span.value}"
    await callback.answer(plain_text(translator, key, locale))
    items = await listing(ListAlertsCommand(actor_id=principal.user_id))
    text, markup = await _alerts_view(
        items, principal, catalog, clock.now(), translator, telegram, locale
    )
    if isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:  # двойное нажатие: тот же текст
            if "message is not modified" not in exc.message:
                raise


@inject
async def feed(
    message: Message,
    locale: Locale,
    translator: FromDishka[Translator],
    listing: FromDishka[ListAlerts],
    queries: FromDishka[JobQueries],
    identity: FromDishka[IdentityApi],
    clock: FromDishka[Clock],
    telegram: FromDishka[TelegramSettings],
    principal: Principal | None = None,
) -> None:
    if principal is None:
        await message.answer(html_text(translator, "bot.language.need_start", locale))
        return
    setup = (plain_text(translator, "bot.alerts.setup", locale), ALERTS_LINK)
    if not await listing(ListAlertsCommand(actor_id=principal.user_id)):
        await message.answer(
            html_text(translator, "bot.feed.no_alerts", locale),
            reply_markup=app_keyboard(telegram, [[setup]]),
        )
        return
    # лента без фото (BrowseJobs ходит за превью в media): в чат идут только строки и кнопки
    filters = await without_blocked(
        identity, FeedFilters(city_id=None, alerts_of=principal.user_id), principal.user_id
    )
    page = await queries.feed(
        filters,
        viewer_id=principal.user_id,
        page=PageRequest(limit=FEED_SHOWN),
        now=clock.now(),
    )
    open_feed = (plain_text(translator, "bot.feed.open", locale), FEED_LINK)
    if not page.items:
        await message.answer(
            html_text(translator, "bot.feed.empty", locale),
            reply_markup=app_keyboard(telegram, [[open_feed], [setup]]),
        )
        return
    lines = [
        html_text(
            translator,
            "bot.feed.line",
            locale,
            title=item.title,
            budget=_budget(item, translator, locale),
        )
        for item in page.items
    ]
    rows = [
        [(_short(item.title), encode_start_param(StartLink(type=LinkType.JOB, id=item.id)))]
        for item in page.items
    ]
    rows.append([open_feed])
    text = "\n".join([html_text(translator, "bot.feed.header", locale), "", *lines])
    await message.answer(text, reply_markup=app_keyboard(telegram, rows))


async def _alerts_view(
    items: list[AlertItem],
    principal: Principal,
    catalog: CatalogApi,
    now: datetime,
    translator: Translator,
    telegram: TelegramSettings,
    locale: Locale,
) -> tuple[str, InlineKeyboardMarkup | None]:
    setup = (plain_text(translator, "bot.alerts.setup", locale), ALERTS_LINK)
    if not items:
        return (
            html_text(translator, "bot.alerts.empty", locale),
            app_keyboard(telegram, [[setup]]),
        )
    lines = []
    for item in items:
        alert = item.alert
        name = await _alert_name(catalog, alert, locale, translator)
        lines.append(
            html_text(
                translator,
                "bot.alerts.line",
                locale,
                alert=name,
                state=_state(alert, now, translator, locale),
                count=item.week_count,
            )
        )
    callbacks: list[InlineKeyboardButton] = []
    if any(item.alert.receives(now) for item in items):
        callbacks += [
            _all_button(principal, span.value, f"bot.alerts.pause_{span.value}", translator, locale)
            for span in PauseSpan
        ]
    if any(item.alert.is_active and item.alert.paused(now) for item in items):
        callbacks.append(_all_button(principal, OFF, "bot.alerts.resume", translator, locale))
    rows: list[list[InlineKeyboardButton]] = [callbacks] if callbacks else []
    if telegram.mini_app_url:
        rows.append([web_app_button(telegram.mini_app_url, *setup)])
    text = "\n".join([html_text(translator, "bot.alerts.header", locale), "", *lines])
    return text, InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def _all_button(
    principal: Principal, arg: str, key: str, translator: Translator, locale: Locale
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=plain_text(translator, key, locale),
        callback_data=encode_callback(
            CallbackData(CallbackAction.ALERTS_PAUSE, principal.user_id, arg)
        ),
    )


def _state(alert: JobAlert, now: datetime, translator: Translator, locale: Locale) -> str:
    if not alert.is_active:
        return plain_text(translator, "bot.alerts.state.off", locale)
    if alert.paused(now) and alert.paused_until is not None:
        until = long_datetime(alert.paused_until, locale)
        return plain_text(translator, "bot.alerts.state.paused", locale, until=until)
    return plain_text(translator, f"bot.alerts.state.{alert.delivery.value}", locale)


async def _alert_name(
    catalog: CatalogApi, alert: JobAlert, locale: Locale, translator: Translator
) -> str:
    """По первой категории подписки («Мастер на час») и «ещё N» — как в карточке B1."""
    first: CategoryId = alert.criteria.category_ids[0]
    label = (await catalog.labels([first])).get(first)
    name = label.get(locale) if label is not None else "—"
    more = len(alert.criteria.category_ids) - 1
    if not more:
        return name
    return plain_text(translator, "bot.alerts.name_more", locale, alert=name, count=more)


def _budget(item: FeedItem, translator: Translator, locale: Locale) -> str:
    if item.budget_type is BudgetType.NEGOTIABLE or item.budget_min is None:
        return plain_text(translator, "bot.feed.negotiable", locale)
    amount = _money(item.budget_max or item.budget_min, locale)
    key = "bot.feed.up_to" if item.budget_type is BudgetType.RANGE else "bot.feed.fixed"
    return plain_text(translator, key, locale, amount=amount)


def _money(para: int, locale: Locale) -> str:
    """Динары без копеек: «5 000» (ru), «5.000» (sr)."""
    separator = " " if locale is Locale.RU else "."
    return f"{para // 100:,}".replace(",", separator)


def _short(title: str) -> str:
    return title if len(title) <= TITLE_CHARS else f"{title[: TITLE_CHARS - 1].rstrip()}…"


async def _keep_app_buttons(callback: CallbackQuery) -> None:
    """«Не подходит» — у карточки остаются только кнопки в Mini App («Открыть заявку»)."""
    message = callback.message
    if not isinstance(message, Message) or message.reply_markup is None:
        return
    rows = [
        row
        for row in message.reply_markup.inline_keyboard
        if all(button.callback_data is None for button in row)
    ]
    await _edit_markup(message, InlineKeyboardMarkup(inline_keyboard=rows))


async def _swap_pause_button(
    callback: CallbackQuery,
    alert: JobAlert,
    *,
    resume: bool,
    translator: Translator,
    locale: Locale,
) -> None:
    """«Пауза подписки» ↔ «Снять паузу» под той же карточкой."""
    message = callback.message
    if not isinstance(message, Message) or message.reply_markup is None:
        return
    old = CallbackAction.ALERT_RESUME if resume else CallbackAction.ALERT_PAUSE
    new = CallbackAction.ALERT_PAUSE if resume else CallbackAction.ALERT_RESUME
    label = "bot.alerts.pause" if resume else "bot.alerts.unpause"
    swapped = InlineKeyboardButton(
        text=plain_text(translator, label, locale),
        callback_data=encode_callback(CallbackData(new, alert.id)),
    )
    rows = [
        [
            swapped if (button.callback_data or "").startswith(f"{old}:") else button
            for button in row
        ]
        for row in message.reply_markup.inline_keyboard
    ]
    await _edit_markup(message, InlineKeyboardMarkup(inline_keyboard=rows))


async def _edit_markup(message: Message, markup: InlineKeyboardMarkup) -> None:
    try:
        await message.edit_reply_markup(reply_markup=markup)
    except TelegramBadRequest as exc:  # двойное нажатие: разметка уже та же
        if "message is not modified" not in exc.message:
            raise
