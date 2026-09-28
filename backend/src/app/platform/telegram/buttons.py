"""Кнопки бота, которые открывают Mini App (ADR-0011, DEVELOPMENT_PLAN 1.6).

Кнопка web_app открывает адрес как есть: Telegram не передаёт в неё start_param, как в
ссылку `t.me/<bot>?startapp=`. Поэтому код deep link едет в `?startapp=` адреса — его читает
Mini App (packages/platform), а экран выбирает тот же кодек, что и для ссылок.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.platform.telegram.deeplinks import parse_start_param

START_QUERY = "startapp"


def mini_app_url(base: str, start_param: str | None = None) -> str:
    """Адрес Mini App с кодом deep link; код, который кодек не разбирает, не передаём."""
    if start_param is None or parse_start_param(start_param) is None:
        return base
    parts = urlsplit(base)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != START_QUERY]
    query.append((START_QUERY, start_param))
    return urlunsplit(parts._replace(query=urlencode(query)))


def open_app_keyboard(url: str, label: str) -> InlineKeyboardMarkup:
    """Одна кнопка web_app: «Открыть «Соседи»», «Открыть правила»."""
    button = InlineKeyboardButton(text=label, web_app=WebAppInfo(url=url))
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


def link_keyboard(url: str, label: str) -> InlineKeyboardMarkup:
    """Одна кнопка-ссылка: например, чат поддержки `https://t.me/<username>`."""
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, url=url)]])
