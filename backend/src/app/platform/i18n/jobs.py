"""Цена, бюджет и время заявки словами языка читателя (ADR-0013).

Одни и те же строки в карточке заявки по подписке B1 (`job.matched`, notifications) и в карточке
«Поделиться» (POST /share, 7.4): «5 000 RSD · сегодня 18:00–21:00» не должно читаться по-разному
в двух сообщениях бота. На входе — машинные значения (коды типа бюджета, единицы и срочности,
суммы в пара, моменты времени), слова — из каталогов `notifications.price.*` и
`notifications.job_matched.*`. На выходе — простой текст: экранирует вызывающий.
"""

from datetime import datetime
from typing import Final

from app.platform.i18n.dates import short_date, short_time
from app.platform.i18n.translator import Translator
from app.platform.kernel.clock import BUSINESS_TZ
from app.platform.kernel.localized import Locale

PRICE_TYPES: Final = frozenset({"fixed", "from", "hourly"})
"""Цена с суммой (`notifications.price.*`); договорная — без суммы."""
BUDGET_UNITS: Final = frozenset({"hour", "m2", "visit", "item", "lesson"})
"""Единица бюджета заявки с подписью «в час», «за м²»…; `work` — за всю работу, без подписи."""
URGENCIES: Final = frozenset({"asap", "today", "this_week", "flexible"})


def money(amount: int, locale: Locale) -> str:
    """Сумма в пара — динарами по правилам языка: «3 500» (ru), «3.500» (sr), копейки — после
    запятой."""
    whole, cents = divmod(amount, 100)
    separator = "\u00a0" if locale is Locale.RU else "."
    text = f"{whole:,}".replace(",", separator)
    return f"{text},{cents:02d}" if cents else text


def price(
    translator: Translator, locale: Locale, kind: str | None, amount: int | None
) -> str | None:
    """Цена словами языка: «3 500 RSD», «от 3 500 RSD», «договорная»; без суммы — None."""
    if kind == "negotiable":
        return _t(translator, "notifications.price.negotiable", locale)
    if kind not in PRICE_TYPES or amount is None:
        return None
    return _t(translator, f"notifications.price.{kind}", locale, amount=money(amount, locale))


def budget(
    translator: Translator,
    locale: Locale,
    *,
    kind: str | None,
    low: int | None,
    high: int | None,
    unit: str | None,
) -> str:
    """Бюджет заявки: «5 000 RSD», «3 000–5 000 RSD в час», «Договорная»."""
    if kind == "negotiable" or low is None:
        return _t(translator, "notifications.job_matched.negotiable", locale)
    amount = money(low, locale)
    if kind == "range" and high is not None:
        text = _t(
            translator,
            "notifications.job_matched.range",
            locale,
            min=amount,
            max=money(high, locale),
        )
    else:
        text = _t(translator, "notifications.price.fixed", locale, amount=amount)
    if unit in BUDGET_UNITS:
        text = f"{text} {_t(translator, f'notifications.job_matched.unit.{unit}', locale)}"
    return text


def when(
    translator: Translator,
    locale: Locale,
    *,
    start: datetime | None,
    end: datetime | None,
    urgency: str | None,
    now: datetime,
) -> str | None:
    """Когда нужно: «сегодня 18:00–21:00», «завтра 10:00», «12 окт. 10:00», иначе по срочности —
    «срочно», «на этой неделе». «Сегодня» — от `now`: момента показа, а не публикации."""
    if start is not None:
        hours = short_time(start)
        if end is not None:
            hours = f"{hours}–{short_time(end)}"
        return f"{_day(translator, locale, start, now)} {hours}"
    if urgency in URGENCIES:
        return _t(translator, f"notifications.job_matched.urgency.{urgency}", locale)
    return None


def _day(translator: Translator, locale: Locale, moment: datetime, now: datetime) -> str:
    today = now.astimezone(BUSINESS_TZ).date()
    day = moment.astimezone(BUSINESS_TZ).date()
    if day == today:
        return _t(translator, "notifications.job_matched.today", locale)
    if (day - today).days == 1:
        return _t(translator, "notifications.job_matched.tomorrow", locale)
    return short_date(moment, locale)


def _t(translator: Translator, key: str, locale: Locale, **params: object) -> str:
    """Текст ключа; ключа нет ни в одном каталоге — сам ключ (пропуск виден в тесте)."""
    return translator.text(key, locale, **params) or key
