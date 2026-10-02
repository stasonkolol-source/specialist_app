"""Дата и время для людей (ADR-0013): по Белграду, в формате языка читателя (CLDR, babel).

Нужны и уведомлениям (шаблоны с датой), и боту (ответ на нажатие кнопки).
"""

from datetime import datetime

import babel
from babel.dates import format_datetime

from app.platform.i18n.catalogs import CATALOG_NAMES
from app.platform.kernel.clock import BUSINESS_TZ
from app.platform.kernel.localized import Locale


def long_datetime(moment: datetime, locale: Locale) -> str:
    """«12 октября 2026 г., 08:30»: длинная дата и время по Белграду на языке `locale`."""
    cldr = babel.Locale.parse(CATALOG_NAMES[locale])
    long_date = cldr.date_formats["long"].pattern
    pattern = cldr.datetime_formats["long"].replace("{1}", long_date).replace("{0}", "HH:mm")
    return format_datetime(moment, pattern, tzinfo=BUSINESS_TZ, locale=cldr)
