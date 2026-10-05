"""Бот moderation (DEVELOPMENT_PLAN 2.5b; ARCHITECTURE §14.1): кнопки карточки кейса в чате
модераторов (карточку рисует infrastructure/chat.py, данные — platform/telegram/callbacks.py).

Нажатие проверяет роль нажавшего в `identity.user_roles` (moderator или admin, как `cli`): без
роли — ответ «решают модераторы», и ничего не происходит. Решение — тем же use case, что `cli`
и админка:
- «Одобрить» — DecideCase `approved` (у апелляции — санкция снята); у спора «Выполнено» —
  ResolveDispute `completed` с причиной `work_done`;
- «Отклонить с причиной» — выбор причины, затем тяжести (лестница санкций): DecideCase
  `rejected`; у спора «Отменить с причиной» — ResolveDispute `cancelled`; у апелляции — сразу
  решение без санкции: прежнее решение остаётся в силе;
- «Эскалировать» — EscalateCase: кейс снова свободен, кнопки остаются для старшего.
Под карточкой — строка итога: что решили и кто (имя модератора в Telegram); кнопки решения
убираются, «Открыть в админке» остаётся. Карточка кейса о фото — подпись к фото: её бот правит
как подпись (editMessageCaption), обычную карточку — как текст.
Пользователю решение доходит как из `cli`: statement of reasons уведомлением. Кейс уже решён —
ответ ошибкой (ErrorMiddleware), карточка не меняется. Кейс устарел (объект изменили после
карточки, ADV-11) — ответ «Версия изменилась — смотрите новую карточку», кнопки решения под
карточкой гаснут, ничего не публикуется: решают новую карточку с новой версией.

Id чата модераторов (K29): в группе `/chatid` или `/start@<бот>` от персонала (moderator или
admin), а также добавление бота в группу персоналом (`my_chat_member`) и переход группы в
супергруппу (`migrate_from_chat_id`: id меняется) — бот отвечает id чата и куда его прописать;
если это уже чат модераторов — так и говорит. Остальным в группах бот молчит: его могут добавить
в любой чат, а id и подсказка нужны только персоналу.
"""

from collections.abc import Awaitable
from typing import Final

import structlog
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import JOIN_TRANSITION, ChatMemberUpdatedFilter, Command, CommandStart
from aiogram.types import CallbackQuery, Chat, ChatMemberUpdated, Message
from dishka.integrations.aiogram import FromDishka, inject

from app.modules.identity.api import IdentityApi
from app.modules.moderation.application.case_card import (
    DISPUTE_DONE_REASON,
    MODERATORS_LOCALE,
    SEVERITY_CODES,
    admin_buttons,
    card_buttons,
    html_text,
    outcome_line,
    plain_text,
    reason_buttons,
    reasons_for,
    severity_buttons,
    superseded_buttons,
)
from app.modules.moderation.application.ports import CaseRepository
from app.modules.moderation.application.use_cases.decide_case import (
    DecideCase,
    DecideCaseCommand,
)
from app.modules.moderation.application.use_cases.resolve_dispute import (
    ResolveDispute,
    ResolveDisputeCommand,
)
from app.modules.moderation.application.use_cases.take_case import (
    EscalateCase,
    EscalateCaseCommand,
)
from app.modules.moderation.domain.cases import Case, EntityType
from app.modules.moderation.domain.sanctions import Severity
from app.platform.contracts.events.moderation import ModerationDecision
from app.platform.i18n.translator import Translator
from app.platform.kernel.ids import CaseId, UserId
from app.platform.kernel.principal import Principal, Role
from app.platform.settings import AppSettings, TelegramSettings, admin_base_url
from app.platform.telegram.aiogram_sender import keyboard
from app.platform.telegram.callbacks import CallbackAction, CallbackData, parse_callback
from app.platform.telegram.port import ButtonLine

log = structlog.get_logger(__name__)

DECIDERS = frozenset({Role.MODERATOR, Role.ADMIN})
GROUPS: Final = frozenset({ChatType.GROUP, ChatType.SUPERGROUP})
CHAT_ID_COMMAND: Final = "chatid"
"""`/chatid` в группе — id чата для TELEGRAM_MODERATORS_CHAT_ID (K29); в меню — у админов групп."""


@inject
async def approve(
    callback: CallbackQuery,
    translator: FromDishka[Translator],
    identity: FromDishka[IdentityApi],
    cases: FromDishka[CaseRepository],
    decide: FromDishka[DecideCase],
    resolve: FromDishka[ResolveDispute],
    app: FromDishka[AppSettings],
    principal: Principal | None = None,
) -> None:
    pressed = await _pressed(callback, translator, identity, cases, principal, app)
    if pressed is None:
        return
    moderator, case, _ = pressed
    if _is_dispute(case):
        await resolve(
            ResolveDisputeCommand(
                case_id=case.id,
                outcome="completed",
                reason_code=DISPUTE_DONE_REASON,
                moderator_id=moderator,
            )
        )
        key = "bot.moderation.decided.dispute_completed"
    else:
        await decide(
            DecideCaseCommand(
                case_id=case.id, verdict=ModerationDecision.APPROVED, moderator_id=moderator
            )
        )
        key = (
            "bot.moderation.decided.appeal_granted"
            if case.is_appeal
            else ("bot.moderation.decided.approved")
        )
    line = outcome_line(translator, key, who=_who(callback))
    await _done(callback, translator, line, buttons=_admin(case, translator, app))


@inject
async def reject(
    callback: CallbackQuery,
    translator: FromDishka[Translator],
    identity: FromDishka[IdentityApi],
    cases: FromDishka[CaseRepository],
    decide: FromDishka[DecideCase],
    app: FromDishka[AppSettings],
    principal: Principal | None = None,
) -> None:
    pressed = await _pressed(callback, translator, identity, cases, principal, app)
    if pressed is None:
        return
    moderator, case, data = pressed
    if data.arg is None:  # «Отклонить с причиной»: сначала причина
        await callback.answer()
        await _buttons(callback, reason_buttons(case, translator))
        return
    if data.arg not in reasons_for(case):
        await callback.answer()
        return
    if not case.is_appeal:  # затем тяжесть: ступень лестницы санкций
        await callback.answer()
        await _buttons(callback, severity_buttons(case.id, data.arg, translator))
        return
    await decide(
        DecideCaseCommand(
            case_id=case.id,
            verdict=ModerationDecision.REJECTED,
            reason_code=data.arg,
            moderator_id=moderator,
        )
    )
    line = outcome_line(
        translator, "bot.moderation.decided.appeal_denied", who=_who(callback), reason=data.arg
    )
    await _done(callback, translator, line, buttons=_admin(case, translator, app))


@inject
async def sanction(
    callback: CallbackQuery,
    translator: FromDishka[Translator],
    identity: FromDishka[IdentityApi],
    cases: FromDishka[CaseRepository],
    decide: FromDishka[DecideCase],
    resolve: FromDishka[ResolveDispute],
    app: FromDishka[AppSettings],
    principal: Principal | None = None,
) -> None:
    pressed = await _pressed(callback, translator, identity, cases, principal, app)
    if pressed is None:
        return
    moderator, case, data = pressed
    code, reason = (data.arg[:1], data.arg[1:]) if data.arg else ("", "")
    if code not in SEVERITY_CODES or reason not in reasons_for(case) or case.is_appeal:
        await callback.answer()
        return
    severity: Severity | None = SEVERITY_CODES[code]
    step = None
    if _is_dispute(case):
        resolution = await resolve(
            ResolveDisputeCommand(
                case_id=case.id,
                outcome="cancelled",
                reason_code=reason,
                moderator_id=moderator,
                severity=severity,
            )
        )
        key, step = "bot.moderation.decided.dispute_cancelled", resolution.sanction
    else:
        decision = await decide(
            DecideCaseCommand(
                case_id=case.id,
                verdict=ModerationDecision.REJECTED,
                reason_code=reason,
                severity=severity,
                moderator_id=moderator,
            )
        )
        key, step = "bot.moderation.decided.rejected", decision.sanction
    sanction_text = step.value if step is not None else "—"
    line = outcome_line(translator, key, who=_who(callback), reason=reason, sanction=sanction_text)
    await _done(callback, translator, line, buttons=_admin(case, translator, app))


@inject
async def escalate(
    callback: CallbackQuery,
    translator: FromDishka[Translator],
    identity: FromDishka[IdentityApi],
    cases: FromDishka[CaseRepository],
    escalate_case: FromDishka[EscalateCase],
    app: FromDishka[AppSettings],
    principal: Principal | None = None,
) -> None:
    pressed = await _pressed(callback, translator, identity, cases, principal, app)
    if pressed is None:
        return
    moderator, case, _ = pressed
    await escalate_case(EscalateCaseCommand(case_id=case.id, moderator_id=moderator))
    line = outcome_line(translator, "bot.moderation.decided.escalated", who=_who(callback))
    # кнопки остаются: решает старший
    buttons = card_buttons(case, translator, admin_base_url(app))
    await _done(callback, translator, line, buttons=buttons)


@inject
async def back(
    callback: CallbackQuery,
    translator: FromDishka[Translator],
    identity: FromDishka[IdentityApi],
    cases: FromDishka[CaseRepository],
    app: FromDishka[AppSettings],
    principal: Principal | None = None,
) -> None:
    pressed = await _pressed(callback, translator, identity, cases, principal, app)
    if pressed is None:
        return
    await callback.answer()
    await _buttons(callback, card_buttons(pressed[1], translator, admin_base_url(app)))


@inject
async def chat_id(
    message: Message,
    translator: FromDishka[Translator],
    identity: FromDishka[IdentityApi],
    telegram: FromDishka[TelegramSettings],
    principal: Principal | None = None,
) -> None:
    """`/chatid`, `/start@<бот>` или переход в супергруппу: персоналу — id этого чата."""
    staff = principal is not None and await _is_staff(identity, principal.user_id)
    text = _chat_id_text(message.chat, staff=staff, translator=translator, telegram=telegram)
    if text is not None:
        await message.answer(text)


@inject
async def added_to_group(
    update: ChatMemberUpdated,
    translator: FromDishka[Translator],
    identity: FromDishka[IdentityApi],
    telegram: FromDishka[TelegramSettings],
) -> None:
    """Бота добавили в группу: добавил персонал — тот же ответ, что на `/chatid` (прослоек
    пользователя у `my_chat_member` нет — пользователь по Telegram id здесь)."""
    author = update.from_user
    user = None if author.is_bot else await identity.by_telegram(author.id)
    staff = user is not None and await _is_staff(identity, user.id)
    text = _chat_id_text(update.chat, staff=staff, translator=translator, telegram=telegram)
    if text is not None:
        await update.answer(text)


async def _is_staff(identity: IdentityApi, user_id: UserId) -> bool:
    return bool(await identity.roles(user_id) & DECIDERS)


def _chat_id_text(
    chat: Chat, *, staff: bool, translator: Translator, telegram: TelegramSettings
) -> str | None:
    """Ответ про id группы; None — не отвечаем: спросил не персонал. Id пишем в лог и тогда —
    по нему видно, что команда дошла, а роли нет."""
    if not staff:
        log.info("moderators_chat_candidate_ignored", chat_id=chat.id)
        return None
    configured = chat.id == telegram.moderators_chat_id
    log.info("moderators_chat_candidate", chat_id=chat.id, title=chat.title, configured=configured)
    key = "bot.moderation.chat.configured" if configured else "bot.moderation.chat.candidate"
    return html_text(translator, key, MODERATORS_LOCALE, chat_id=chat.id)


async def _pressed(
    callback: CallbackQuery,
    translator: Translator,
    identity: IdentityApi,
    cases: CaseRepository,
    principal: Principal | None,
    app: AppSettings,
) -> tuple[UserId, Case, CallbackData] | None:
    """Модератор, кейс и данные кнопки; None — ответ уже дан: не модератор, нет кейса или кейс
    устарел (тогда кнопки под карточкой гаснут)."""
    data = parse_callback(callback.data)
    if data is None:
        await callback.answer()
        return None
    if principal is None or not (await identity.roles(principal.user_id)) & DECIDERS:
        text = plain_text(translator, "bot.moderation.not_moderator", MODERATORS_LOCALE)
        await callback.answer(text, show_alert=True)
        return None
    case = await cases.get(CaseId(data.id))
    if case is None:
        text = plain_text(translator, "errors.case_not_found", MODERATORS_LOCALE)
        await callback.answer(text, show_alert=True)
        return None
    if case.is_superseded:
        text = plain_text(translator, "bot.moderation.superseded", MODERATORS_LOCALE)
        await callback.answer(text, show_alert=True)
        await _buttons(callback, superseded_buttons(case.id, translator, admin_base_url(app)))
        return None
    return principal.user_id, case, data


def _is_dispute(case: Case) -> bool:
    return case.entity_type is EntityType.DISPUTE and not case.is_appeal


def _admin(case: Case, translator: Translator, app: AppSettings) -> tuple[ButtonLine, ...]:
    """Под решённой карточкой — только «Открыть в админке» (история, доказательства)."""
    return admin_buttons(case.id, translator, admin_base_url(app))


def _who(callback: CallbackQuery) -> str:
    """Кто решил: имя модератора в Telegram (чат модераторов — свои люди)."""
    user = callback.from_user
    return f"@{user.username}" if user.username else user.full_name


async def _done(
    callback: CallbackQuery,
    translator: Translator,
    line: str,
    *,
    buttons: tuple[ButtonLine, ...] = (),
) -> None:
    await callback.answer(plain_text(translator, "bot.moderation.done", MODERATORS_LOCALE))
    message = callback.message
    if not isinstance(message, Message):
        return
    text = f"{message.html_text}\n\n{line}"
    if message.photo or (message.text is None and message.caption is not None):
        # карточка кейса о фото — подпись к нему
        await _edit(message.edit_caption(caption=text, reply_markup=keyboard(buttons)))
        return
    await _edit(message.edit_text(text, reply_markup=keyboard(buttons)))


async def _buttons(callback: CallbackQuery, buttons: tuple[ButtonLine, ...]) -> None:
    if isinstance(callback.message, Message):
        await _edit(callback.message.edit_reply_markup(reply_markup=keyboard(buttons)))


async def _edit(request: Awaitable[object]) -> None:
    try:
        await request
    except TelegramBadRequest as exc:  # двойное нажатие: то же сообщение Telegram отвергает
        if "message is not modified" not in exc.message:
            raise


def create_router() -> Router:
    """Новый роутер на каждый вызов: роутер aiogram подключается только к одному диспетчеру."""
    router = Router(name="moderation")
    for action, handler in (
        (CallbackAction.CASE_APPROVE, approve),
        (CallbackAction.CASE_REJECT, reject),
        (CallbackAction.CASE_SANCTION, sanction),
        (CallbackAction.CASE_ESCALATE, escalate),
        (CallbackAction.CASE_BACK, back),
    ):
        router.callback_query.register(handler, F.data.startswith(f"{action}:"))
    # id чата модераторов (K29): только группы — личные /start и прочее у других модулей
    groups = F.chat.type.in_(GROUPS)
    router.message.register(chat_id, Command(CHAT_ID_COMMAND), groups)
    router.message.register(chat_id, CommandStart(), groups)
    router.message.register(chat_id, F.migrate_from_chat_id, groups)
    router.my_chat_member.register(added_to_group, ChatMemberUpdatedFilter(JOIN_TRANSITION), groups)
    return router
