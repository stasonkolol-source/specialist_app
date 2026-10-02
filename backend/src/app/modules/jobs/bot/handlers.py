"""Бот jobs (DEVELOPMENT_PLAN 5.1, 5.6): кнопки уведомлений о сроке заявки — `job.expiring` и
`job.expired` — и приглашения `job.invited` (ARCHITECTURE §11.3). Кнопки рисует notifications,
данные — общий кодек platform/telegram/callbacks.py.

- «Продлить» — тот же ExtendJob, что `POST /jobs/{id}/extend` и S23: сообщение заменяется
  итогом «продлена до …».
- «Закрыть» сначала спрашивает причину кнопками под тем же сообщением: у `job.expiring`
  («исполнитель найден») — где нашёлся, у `job.expired` — все четыре причины; рядом остаётся
  «Продлить», если передумали. Выбор вызывает CloseJob, как S23.
- «Откликнуться: «Могу сегодня»» — тот же Respond, что S16, с предложением из шаблона: ответ на
  нажатие «Отклик отправлен…», кнопки шаблонов под сообщением пропадают («Посмотреть заявку»
  остаётся). Мест нет, уже откликались, лимит дня, шаблон удалён — текстом ошибки.
Владелец — по Telegram: чужая или удалённая заявка — «не найдена» (ErrorMiddleware).
"""

from typing import Final

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dishka.integrations.aiogram import FromDishka, inject

from app.modules.jobs.application.dto import JobView
from app.modules.jobs.application.ports import JobQueries
from app.modules.jobs.application.use_cases.close_job import CloseJob, CloseJobCommand
from app.modules.jobs.application.use_cases.extend_job import ExtendJob, ExtendJobCommand
from app.modules.jobs.application.use_cases.respond_with_template import (
    RespondWithTemplate,
    RespondWithTemplateCommand,
)
from app.modules.jobs.domain.job import CLOSABLE, MAX_EXTENSIONS, CloseReason, JobId, JobStatus
from app.modules.jobs.domain.template import TemplateId
from app.modules.jobs.errors import JobNotFoundError, JobNotOpenError
from app.platform.i18n.dates import long_datetime
from app.platform.i18n.translator import Translator
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Principal
from app.platform.telegram.callbacks import (
    CallbackAction,
    CallbackData,
    arg_ref,
    encode_callback,
    parse_callback,
)
from app.platform.telegram.texts import html_text, plain_text

FOUND: Final = "found"
"""Аргумент «Закрыть» из `job.expiring`: исполнитель найден — спросить, где."""
REASONS: Final = (
    CloseReason.HIRED_HERE,
    CloseReason.HIRED_ELSEWHERE,
    CloseReason.NOT_NEEDED,
    CloseReason.NO_SUITABLE,
)
FOUND_REASONS: Final = (CloseReason.HIRED_HERE, CloseReason.HIRED_ELSEWHERE)
EXTENDABLE: Final = frozenset({JobStatus.PUBLISHED, JobStatus.EXPIRED})


@inject
async def extend(
    callback: CallbackQuery,
    locale: Locale,
    translator: FromDishka[Translator],
    extend_job: FromDishka[ExtendJob],
    queries: FromDishka[JobQueries],
    principal: Principal | None = None,
) -> None:
    data = parse_callback(callback.data)
    if principal is None or data is None:
        await callback.answer()
        return
    job_id = JobId(data.id)
    await extend_job(ExtendJobCommand(actor_id=principal.user_id, job_id=job_id))
    job = await queries.view(job_id)
    await callback.answer()
    if job is not None and job.expires_at is not None:
        until = long_datetime(job.expires_at, locale)
        await _replace(
            callback,
            html_text(translator, "bot.jobs.extended", locale, title=job.title, until=until),
        )


@inject
async def close(
    callback: CallbackQuery,
    locale: Locale,
    translator: FromDishka[Translator],
    close_job: FromDishka[CloseJob],
    queries: FromDishka[JobQueries],
    principal: Principal | None = None,
) -> None:
    data = parse_callback(callback.data)
    if principal is None or data is None:
        await callback.answer()
        return
    job_id = JobId(data.id)
    job = await queries.view(job_id)
    if job is None or job.client_id != principal.user_id:
        raise JobNotFoundError(job_id=job_id)
    if job.status not in CLOSABLE:  # уже закрыта: причину не спрашиваем
        raise JobNotOpenError(job_id=job_id, job_status=job.status.value)
    if data.arg is None or data.arg == FOUND:
        await callback.answer()
        found = data.arg == FOUND
        question = "bot.jobs.found_question" if found else "bot.jobs.close_question"
        await _replace(
            callback,
            html_text(translator, question, locale, title=job.title),
            _reasons(job, FOUND_REASONS if found else REASONS, translator, locale),
        )
        return
    reason = next((r for r in REASONS if r.value == data.arg), None)
    if reason is None:
        await callback.answer()
        return
    await close_job(CloseJobCommand(actor_id=principal.user_id, job_id=job_id, reason=reason))
    await callback.answer()
    await _replace(callback, html_text(translator, "bot.jobs.closed", locale, title=job.title))


@inject
async def respond(
    callback: CallbackQuery,
    locale: Locale,
    translator: FromDishka[Translator],
    respond_with_template: FromDishka[RespondWithTemplate],
    principal: Principal | None = None,
) -> None:
    data = parse_callback(callback.data)
    template_id = arg_ref(data.arg) if data is not None else None
    if principal is None or data is None or template_id is None:
        await callback.answer()
        return
    template, _ = await respond_with_template(
        RespondWithTemplateCommand(
            actor_id=principal.user_id,
            trust_level=principal.trust_level,
            job_id=JobId(data.id),
            template_id=TemplateId(template_id),
        )
    )
    await callback.answer(
        plain_text(translator, "bot.jobs.responded", locale, template=template.title)
    )
    await _drop_template_buttons(callback)


async def _drop_template_buttons(callback: CallbackQuery) -> None:
    """Откликнулись — кнопки шаблонов больше не нужны; «Посмотреть заявку» остаётся."""
    message = callback.message
    if not isinstance(message, Message) or message.reply_markup is None:
        return
    rows = [
        row
        for row in message.reply_markup.inline_keyboard
        if not any(
            (button.callback_data or "").startswith(f"{CallbackAction.JOB_RESPOND}:")
            for button in row
        )
    ]
    try:
        await message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    except TelegramBadRequest as exc:  # двойное нажатие: разметка уже та же
        if "message is not modified" not in exc.message:
            raise


def _reasons(
    job: JobView, reasons: tuple[CloseReason, ...], translator: Translator, locale: Locale
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=plain_text(translator, f"bot.jobs.reason.{reason.value}", locale),
                callback_data=encode_callback(
                    CallbackData(CallbackAction.JOB_CLOSE, job.id, reason.value)
                ),
            )
        ]
        for reason in reasons
    ]
    if job.status in EXTENDABLE and job.extensions_count < MAX_EXTENSIONS:  # передумали
        rows.append(
            [
                InlineKeyboardButton(
                    text=plain_text(translator, "bot.jobs.extend", locale),
                    callback_data=encode_callback(CallbackData(CallbackAction.JOB_EXTEND, job.id)),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _replace(
    callback: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None
) -> None:
    """Заменить сообщение с кнопками итогом или вопросом; старое (недоступное боту) — оставить."""
    if not isinstance(callback.message, Message):
        return
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:  # двойное нажатие: тот же текст Telegram отвергает
        if "message is not modified" not in exc.message:
            raise


def create_router() -> Router:
    """Новый роутер на каждый вызов: роутер aiogram подключается только к одному диспетчеру."""
    router = Router(name="jobs")
    router.callback_query.register(extend, F.data.startswith(f"{CallbackAction.JOB_EXTEND}:"))
    router.callback_query.register(close, F.data.startswith(f"{CallbackAction.JOB_CLOSE}:"))
    router.callback_query.register(respond, F.data.startswith(f"{CallbackAction.JOB_RESPOND}:"))
    return router
