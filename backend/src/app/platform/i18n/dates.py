"""Дата и время для людей (ADR-0013): по Белграду, в формате языка читателя (CLDR, babel).

Нужны и уведомлениям (шаблоны с датой), и боту (ответ на нажатие кнопки).
"""

import re
from datetime import datetime

import babel
from babel.dates import format_date, format_datetime

from app.platform.i18n.catalogs import CATALOG_NAMES
from app.platform.kernel.clock import BUSINESS_TZ
from app.platform.kernel.localized import Locale

_CYRILLIC = re.compile(r"[Ѐ-ӿ]")


def long_datetime(moment: datetime, locale: Locale, *, genitive: bool = False) -> str:
    """«12 октября 2026 г., 08:30»: длинная дата и время по Белграду на языке `locale`.

    `genitive` — дата после предлога или в значении «когда» («до 12 октября», «продлена до …»):
    сербский месяц тогда в родительном падеже — «do 12. oktobra 2026. 08:30». У CLDR сербские
    месяцы в именительном («12. oktobar»), русский CLDR и так пишет родительный.
    """
    cldr = babel.Locale.parse(CATALOG_NAMES[locale])
    long_date = cldr.date_formats["long"].pattern
    if genitive and cldr.language == "sr":
        month = cldr.months["format"]["wide"][moment.astimezone(BUSINESS_TZ).month]
        long_date = long_date.replace("MMMM", f"'{serbian_genitive(month)}'")
    pattern = cldr.datetime_formats["long"].replace("{1}", long_date).replace("{0}", "HH:mm")
    return format_datetime(moment, pattern, tzinfo=BUSINESS_TZ, locale=cldr)


def serbian_genitive(month: str) -> str:
    """Сербский месяц в родительном: «oktobar» → «oktobra», «mart» → «marta» (и кириллицей).

    Беглое «а» у -bar (septembar → septembra), остальным — «+a»; уже на «-a» — как есть.
    """
    if month.endswith(("a", "а")):
        return month
    cyrillic = _CYRILLIC.search(month) is not None
    if month.endswith(("bar", "бар")):
        return f"{month[:-2]}{'ра' if cyrillic else 'ra'}"
    return f"{month}{'а' if cyrillic else 'a'}"


def short_date(moment: datetime, locale: Locale) -> str:
    """«12 окт.»: день и месяц по Белграду на языке `locale` (карточка заявки B1)."""
    cldr = babel.Locale.parse(CATALOG_NAMES[locale])
    return format_date(moment.astimezone(BUSINESS_TZ).date(), "d MMM", locale=cldr)


def short_time(moment: datetime) -> str:
    """«18:00» по Белграду: время одинаковое на всех языках «Соседей»."""
    return moment.astimezone(BUSINESS_TZ).strftime("%H:%M")
