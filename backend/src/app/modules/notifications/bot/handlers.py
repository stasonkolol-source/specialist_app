"""Бот notifications (DEVELOPMENT_PLAN 2.3b, 4.9, ADR-0011): статус канала и `/settings`.

Остановил бота в личном чате (`my_chat_member` → `kicked`) — канал telegram выключается;
запустил снова (`member`) — включается, как после /start. Апдейт человека, которого нет
среди пользователей (ещё не нажал /start), ничего не меняет: канал появится с /start.

`/settings` — уведомления в боте по группам и тихие часы: нажатие переключает и перерисовывает
кнопки; «Все настройки» — S43, «Удалить аккаунт» — S45 (язык — /language).
"""

from typing import Final

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from dishka.integrations.aiogram import FromDishka, inject

from app.modules.identity.api import IdentityApi
from app.modules.notifications.application.ports import NotificationQuery
from app.modules.notifications.application.use_cases.block_telegram_channel import (
    BlockTelegramChannel,
    BlockTelegramChannelCommand,
)
from app.modules.notifications.application.use_cases.grant_telegram_write_access import (
    GrantTelegramWriteAccess,
    GrantTelegramWriteAccessCommand,
)
from app.modules.notifications.application.use_cases.toggle_bot_setting import (
    ToggleBotSetting,
    ToggleBotSettingCommand,
)
from app.modules.notifications.domain.catalog import Channel, EventGroup
from app.modules.notifications.domain.channel import GrantedVia
from app.modules.notifications.domain.settings import NotificationSettings
from app.platform.i18n.translator import Translator
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Principal
from app.platform.settings import TelegramSettings
from app.platform.telegram.buttons import mini_app_url
from app.platform.telegram.deeplinks import LinkSection, LinkType, StartLink, encode_start_param
from app.platform.telegram.texts import html_text, plain_text

SETTINGS_CALLBACK: Final = "nset:"
QUIET: Final = "quiet"
GROUPS: Final = (
    EventGroup.JOB_MATCHES,
    EventGroup.RESPONSES,
    EventGroup.MESSAGES,
    EventGroup.DEALS,
    EventGroup.MARKETING,
)
"""Группы в порядке S43; служебная `account` не выключается и здесь не показывается."""
ALL_SETTINGS: Final = encode_start_param(
    StartLink(type=LinkType.MINE, section=LinkSection.SETTINGS)
)
DELETION: Final = encode_start_param(StartLink(type=LinkType.MINE, section=LinkSection.DELETION))


@inject
async def member_status(
    update: ChatMemberUpdated,
    identity: FromDishka[IdentityApi],
    block: FromDishka[BlockTelegramChannel],
    grant: FromDishka[GrantTelegramWriteAccess],
) -> None:
    if update.from_user.is_bot:
        return
    user = await identity.by_telegram(update.from_user.id)
    if user is None:
        return
    status = update.new_chat_member.status
    if status == ChatMemberStatus.KICKED:
        await block(BlockTelegramChannelCommand(user_id=user.id, at=update.date))
    elif status == ChatMemberStatus.MEMBER:
        await grant(
            GrantTelegramWriteAccessCommand(
                user_id=user.id, via=GrantedVia.BOT_START, at=update.date
            )
        )


@inject
async def settings_command(
    message: Message,
    locale: Locale,
    translator: FromDishka[Translator],
    query: FromDishka[NotificationQuery],
    telegram: FromDishka[TelegramSettings],
    principal: Principal | None = None,
) -> None:
    if principal is None:
        await message.answer(html_text(translator, "bot.settings.start", locale))
        return
    current = await query.settings(principal.user_id)
    await message.answer(
        html_text(translator, "bot.settings.text", locale),
        reply_markup=_keyboard(current, translator, locale, telegram.mini_app_url),
    )


@inject
async def toggle(
    callback: CallbackQuery,
    locale: Locale,
    translator: FromDishka[Translator],
    toggle_setting: FromDishka[ToggleBotSetting],
    telegram: FromDishka[TelegramSettings],
    principal: Principal | None = None,
) -> None:
    value = (callback.data or "").removeprefix(SETTINGS_CALLBACK)
    group = next((g for g in GROUPS if g.value == value), None)
    if principal is None or (group is None and value != QUIET):
        await callback.answer()
        return
    changed = await toggle_setting(ToggleBotSettingCommand(user_id=principal.user_id, group=group))
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    try:
        await callback.message.edit_reply_markup(
            reply_markup=_keyboard(changed, translator, locale, telegram.mini_app_url)
        )
    except TelegramBadRequest as exc:  # двойное нажатие: та же клавиатура
        if "message is not modified" not in exc.message:
            raise


def _keyboard(
    current: NotificationSettings, translator: Translator, locale: Locale, mini_app: str | None
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for group in GROUPS:
        on = current.preferences.allows(group, Channel.TELEGRAM)
        name = plain_text(translator, f"bot.settings.group.{group.value}", locale)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{'✅' if on else '▫️'} {name}",
                    callback_data=f"{SETTINGS_CALLBACK}{group.value}",
                )
            ]
        )
    quiet = current.quiet_hours
    key = "bot.settings.quiet_on" if quiet.enabled else "bot.settings.quiet_off"
    rows.append(
        [
            InlineKeyboardButton(
                text=plain_text(
                    translator,
                    key,
                    locale,
                    start=quiet.start.strftime("%H:%M"),
                    end=quiet.end.strftime("%H:%M"),
                ),
                callback_data=f"{SETTINGS_CALLBACK}{QUIET}",
            )
        ]
    )
    if mini_app is not None:
        for label, link in (("bot.settings.all", ALL_SETTINGS), ("bot.settings.delete", DELETION)):
            rows.append(
                [
                    InlineKeyboardButton(
                        text=plain_text(translator, label, locale),
                        web_app=WebAppInfo(url=mini_app_url(mini_app, link)),
                    )
                ]
            )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def create_router() -> Router:
    """Новый роутер на каждый вызов: роутер aiogram подключается только к одному диспетчеру."""
    router = Router(name="notifications")
    private = F.chat.type == "private"
    router.my_chat_member.register(member_status, private)
    router.message.register(settings_command, Command("settings"), private)
    router.callback_query.register(toggle, F.data.startswith(SETTINGS_CALLBACK))
    return router
