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
Под карточкой — строка итога: что решили и кто (имя модератора в Telegram); кнопки убираются.
Пользователю решение доходит как из `cli`: statement of reasons уведомлением. Кейс уже решён —
ответ ошибкой (ErrorMiddleware), карточка не меняется.
"""

from collections.abc import Awaitable

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from dishka.integrations.aiogram import FromDishka, inject

from app.modules.identity.api import IdentityApi
from app.modules.moderation.application.case_card import (
    DISPUTE_DONE_REASON,
    MODERATORS_LOCALE,
    SEVERITY_CODES,
    card_buttons,
    outcome_line,
    plain_text,
    reason_buttons,
    reasons_for,
    severity_buttons,
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
from app.platform.telegram.aiogram_sender import keyboard
from app.platform.telegram.callbacks import CallbackAction, CallbackData, parse_callback
from app.platform.telegram.port import ButtonLine

DECIDERS = frozenset({Role.MODERATOR, Role.ADMIN})


@inject
async def approve(
    callback: CallbackQuery,
    translator: FromDishka[Translator],
    identity: FromDishka[IdentityApi],
    cases: FromDishka[CaseRepository],
    decide: FromDishka[DecideCase],
    resolve: FromDishka[ResolveDispute],
    principal: Principal | None = None,
) -> None:
    pressed = await _pressed(callback, translator, identity, cases, principal)
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
    await _done(callback, translator, outcome_line(translator, key, who=_who(callback)))


@inject
async def reject(
    callback: CallbackQuery,
    translator: FromDishka[Translator],
    identity: FromDishka[IdentityApi],
    cases: FromDishka[CaseRepository],
    decide: FromDishka[DecideCase],
    principal: Principal | None = None,
) -> None:
    pressed = await _pressed(callback, translator, identity, cases, principal)
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
    await _done(callback, translator, line)


@inject
async def sanction(
    callback: CallbackQuery,
    translator: FromDishka[Translator],
    identity: FromDishka[IdentityApi],
    cases: FromDishka[CaseRepository],
    decide: FromDishka[DecideCase],
    resolve: FromDishka[ResolveDispute],
    principal: Principal | None = None,
) -> None:
    pressed = await _pressed(callback, translator, identity, cases, principal)
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
    await _done(callback, translator, line)


@inject
async def escalate(
    callback: CallbackQuery,
    translator: FromDishka[Translator],
    identity: FromDishka[IdentityApi],
    cases: FromDishka[CaseRepository],
    escalate_case: FromDishka[EscalateCase],
    principal: Principal | None = None,
) -> None:
    pressed = await _pressed(callback, translator, identity, cases, principal)
    if pressed is None:
        return
    moderator, case, _ = pressed
    await escalate_case(EscalateCaseCommand(case_id=case.id, moderator_id=moderator))
    line = outcome_line(translator, "bot.moderation.decided.escalated", who=_who(callback))
    # кнопки остаются: решает старший
    await _done(callback, translator, line, buttons=card_buttons(case, translator))


@inject
async def back(
    callback: CallbackQuery,
    translator: FromDishka[Translator],
    identity: FromDishka[IdentityApi],
    cases: FromDishka[CaseRepository],
    principal: Principal | None = None,
) -> None:
    pressed = await _pressed(callback, translator, identity, cases, principal)
    if pressed is None:
        return
    await callback.answer()
    await _buttons(callback, card_buttons(pressed[1], translator))


async def _pressed(
    callback: CallbackQuery,
    translator: Translator,
    identity: IdentityApi,
    cases: CaseRepository,
    principal: Principal | None,
) -> tuple[UserId, Case, CallbackData] | None:
    """Модератор, кейс и данные кнопки; None — ответ уже дан: не модератор или нет кейса."""
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
    return principal.user_id, case, data


def _is_dispute(case: Case) -> bool:
    return case.entity_type is EntityType.DISPUTE and not case.is_appeal


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
    if not isinstance(callback.message, Message):
        return
    text = f"{callback.message.html_text}\n\n{line}"
    await _edit(callback.message.edit_text(text, reply_markup=keyboard(buttons)))


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
    return router
