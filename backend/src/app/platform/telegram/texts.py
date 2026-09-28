"""Тексты бота в HTML (Bot API parse_mode=HTML, DEVELOPMENT_PLAN 1.6, ADR-0011).

Шаблон из каталога — доверенный HTML: в нём можно `<b>`, `<i>`, переносы строк. Параметры —
недоверенные (имя из Telegram, название из данных) и экранируются: `<b>Ana & Co</b>` в имени
приходит человеку текстом, а не разметкой. Ключа нет ни в одном каталоге — возвращается сам
ключ: пропуск виден в тесте и в чате, а не превращается в пустое сообщение.
"""

import html
from typing import Final

from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.platform.i18n.translator import Translator
from app.platform.kernel.localized import Locale

BOT_DEFAULTS: Final = DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True)
"""Настройки клиента Bot API: все тексты бота — HTML, превью ссылок выключены."""


def html_text(translator: Translator, key: str, locale: Locale, **params: object) -> str:
    safe = {name: html.escape(str(value), quote=False) for name, value in params.items()}
    return translator.text(key, locale, **safe) or key


def plain_text(translator: Translator, key: str, locale: Locale, **params: object) -> str:
    """Подпись кнопки или команды: Telegram показывает её как есть, без разметки."""
    return translator.text(key, locale, **params) or key
