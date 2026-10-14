"""Карточка concierge в чате модераторов (DEVELOPMENT_PLAN 7.1; аудит роста п. 1): заявка двадцать
минут без откликов — команде, пока клиент не ушёл искать мастера в чатах.

Чат модераторов — он же чат concierge (K29): карточку видит та же команда, что решает кейсы. По ней
concierge подбирает исполнителя руками («3 предложения за час»): что нужно, где, за сколько и
когда, сколько ей уже никто не ответил и скольким подписчикам она ушла:

    ⏳ Заявка без откликов
    📄 Повесить люстру в спальне
    Мастер на час · Лиман, Нови-Сад
    5 000 RSD · срочно · сегодня 18:00–21:00
    0 откликов за 20 мин · разослано подписчикам: 7 · ждут проверки: 1
    🔗 https://t.me/<бот>?startapp=j_…

Ссылка `j_` — строкой (её копируют и пересылают мастерам) и кнопкой «Открыть заявку». Кнопка —
ссылка, а не web_app: в группах Telegram web_app-кнопки не пускает. Граница приватности — как у
карточки кейса: только то, что видят исполнители на S15, без клиента, описания, адреса и точки.
Тексты — на языке чата модераторов.
"""

import html
from datetime import datetime
from typing import Final

from app.modules.moderation.application.case_card import MODERATORS_LOCALE, html_text, plain_text
from app.modules.moderation.application.dto import QuietJob
from app.platform.i18n.jobs import budget, when
from app.platform.i18n.translator import Translator
from app.platform.telegram.deeplinks import LinkType, StartLink, encode_start_param, startapp_url
from app.platform.telegram.port import ButtonLine, LinkButton

MINUTE: Final = 60
URGENT: Final = "asap"


def job_url(job: QuietJob, bot_username: str) -> str:
    """`https://t.me/<бот>?startapp=j_<id>`: Mini App на экране заявки у любого, кто откроет."""
    start = encode_start_param(StartLink(type=LinkType.JOB, id=job.job_id))
    return startapp_url(bot_username, start)


def quiet_job_text(
    job: QuietJob, translator: Translator, *, now: datetime, bot_username: str | None
) -> str:
    """HTML карточки: пользовательское (название) экранировано, остальное — слова каталога."""
    locale = MODERATORS_LOCALE

    def t(key: str, **params: object) -> str:
        return html_text(translator, key, locale, **params)

    where = _joined(job.category, job.place)
    window = when(
        translator, locale, start=job.preferred_from, end=job.preferred_to, urgency=None, now=now
    )
    # срочность словом — всегда, если «срочно»; остальные («сегодня», «на этой неделе») окно
    # времени и так называет
    urgency = (
        when(translator, locale, start=None, end=None, urgency=job.urgency, now=now)
        if window is None or job.urgency == URGENT
        else None
    )
    amount = budget(
        translator,
        locale,
        kind=job.budget_type,
        low=job.budget_min,
        high=job.budget_max,
        unit=job.budget_unit,
    )
    silence = t(
        "bot.concierge.silence",
        minutes=max(1, int(job.waited.total_seconds()) // MINUTE),
        count=job.notified,
    )
    if job.pending:
        silence += " · " + t("bot.concierge.pending", count=job.pending)
    lines = [
        t("bot.concierge.title"),
        t("bot.concierge.job", title=job.title),
        *([html.escape(where, quote=False)] if where else []),
        html.escape(_joined(amount, urgency, window) or amount, quote=False),
        silence,
    ]
    if bot_username:
        lines.append(f"🔗 {html.escape(job_url(job, bot_username), quote=False)}")
    return "\n".join(lines)


def quiet_job_buttons(
    job: QuietJob, translator: Translator, bot_username: str | None
) -> tuple[ButtonLine, ...]:
    """«Открыть заявку» — ссылкой `t.me/<бот>?startapp=j_…`; без имени бота кнопки нет."""
    if not bot_username:
        return ()
    label = plain_text(translator, "bot.concierge.open", MODERATORS_LOCALE)
    return (LinkButton(text=label, url=job_url(job, bot_username)),)


def _joined(*parts: str | None) -> str | None:
    """Непустые части строки через « · »."""
    return " · ".join(part for part in parts if part) or None
