"""Бот reviews (DEVELOPMENT_PLAN 7.3, B2; ARCHITECTURE §11.3): звёзды под «Оцените работу»
(`review.request`, кнопки рисует notifications, данные — platform/telegram/callbacks.py).

Нажатие — тот же LeaveReview, что `POST /deals/{id}/review` и S27: отзыв с одной оценкой уходит
на автопроверку. Отзыв уже есть — «уже оставили», срок прошёл — «срок вышел». Сообщение
заменяется итогом без кнопок. Чужая сделка — «не найдена» (ErrorMiddleware).
"""

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message
from dishka.integrations.aiogram import FromDishka, inject

from app.modules.reviews.application.use_cases.leave_review import (
    LeaveReview,
    LeaveReviewCommand,
)
from app.modules.reviews.domain.review import STARS
from app.modules.reviews.errors import ReviewExistsError, ReviewNotAllowedError
from app.platform.i18n.translator import Translator
from app.platform.kernel.ids import DealId
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Principal
from app.platform.telegram.callbacks import CallbackAction, parse_callback
from app.platform.telegram.texts import html_text

WINDOW_CLOSED = "window_closed"


@inject
async def rate(
    callback: CallbackQuery,
    locale: Locale,
    translator: FromDishka[Translator],
    leave: FromDishka[LeaveReview],
    principal: Principal | None = None,
) -> None:
    data = parse_callback(callback.data)
    rating = int(data.arg) if data is not None and data.arg and data.arg.isdigit() else 0
    if principal is None or data is None or not 1 <= rating <= STARS:
        await callback.answer()
        return
    try:
        await leave(
            LeaveReviewCommand(actor_id=principal.user_id, deal_id=DealId(data.id), rating=rating)
        )
    except ReviewExistsError:
        text = html_text(translator, "bot.reviews.exists", locale)
    except ReviewNotAllowedError as exc:
        if exc.params.get("reason") != WINDOW_CLOSED:
            raise
        text = html_text(translator, "bot.reviews.closed", locale)
    else:
        stars = "★" * rating + "☆" * (STARS - rating)
        text = html_text(translator, "bot.reviews.rated", locale, stars=stars)
    await callback.answer()
    await _replace(callback, text)


async def _replace(callback: CallbackQuery, text: str) -> None:
    """Заменить просьбу итогом без кнопок; старое (недоступное боту) сообщение — оставить."""
    if not isinstance(callback.message, Message):
        return
    try:
        await callback.message.edit_text(text, reply_markup=None)
    except TelegramBadRequest as exc:  # двойное нажатие: тот же текст Telegram отвергает
        if "message is not modified" not in exc.message:
            raise


def create_router() -> Router:
    """Новый роутер на каждый вызов: роутер aiogram подключается только к одному диспетчеру."""
    router = Router(name="reviews")
    router.callback_query.register(rate, F.data.startswith(f"{CallbackAction.REVIEW_RATE}:"))
    return router
