"""Кнопки бота jobs, которые открывают Mini App (ADR-0011): подпись и код deep link экрана."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.platform.settings import TelegramSettings
from app.platform.telegram.buttons import mini_app_url


def web_app_button(base: str, label: str, link: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=label, web_app=WebAppInfo(url=mini_app_url(base, link)))


def app_keyboard(
    telegram: TelegramSettings, rows: list[list[tuple[str, str]]]
) -> InlineKeyboardMarkup | None:
    """Кнопки web_app (подпись, код deep link экрана); без адреса Mini App — без кнопок."""
    base = telegram.mini_app_url
    if not base:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[web_app_button(base, label, link) for label, link in row] for row in rows]
    )
