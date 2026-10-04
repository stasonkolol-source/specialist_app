"""Алерт ликвидности (DEVELOPMENT_PLAN 6.6, ARCHITECTURE §16.5): response rate@4h ниже порога.

Раз в сутки утром считается response rate@4h по заявкам последних 7 дней (окно 4 ч у них уже
закрылось) — в итоге и по парам «город × категория». Ниже порога `ANALYTICS_RESPONSE_RATE_
ALERT_THRESHOLD` — сообщение в чат модераторов (он же чат concierge, 7.1), если он задан, а без
него — предупреждение в лог и Sentry. Меньше `…_MIN_JOBS` заявок — молчим: на трёх заявках
доля ничего не значит. Раз в сутки, а не ежечасно: пока ликвидность не вернулась, алерт
повторится завтра, и отдельное состояние «уже предупредили» не нужно.
"""

import html
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sentry_sdk
import structlog
from sqlalchemy.ext.asyncio import AsyncConnection

from app.platform.analytics.liquidity import (
    Ratio,
    Window,
    pair_liquidity,
    pair_names,
    reporting_connection,
)
from app.platform.queue.tasks import PeriodicRun, periodic
from app.platform.settings import AnalyticsSettings, DbSettings, TelegramSettings
from app.platform.telegram.port import OutgoingMessage, TelegramSender

log = structlog.get_logger(__name__)

LOOKBACK = timedelta(days=7)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResponseRateAlert:
    overall: Ratio
    threshold: float
    pairs: tuple[tuple[str, Ratio], ...]
    """Пары ниже порога с достаточным числом заявок: «Нови-Сад × Ремонт»."""

    def text(self) -> str:
        lines = [
            "<b>Ликвидность падает</b>",
            f"Response rate@4h за 7 дней — {_percent(self.overall)}, "
            f"порог {self.threshold * 100:.0f}%.",
        ]
        if self.pairs:
            lines.append("Ниже порога:")
            lines += [f"• {html.escape(name)} — {_percent(ratio)}" for name, ratio in self.pairs]
        lines.append("Откликнуться на заявки без ответа — concierge «3 предложения за час».")
        return "\n".join(lines)


async def check_response_rate(
    conn: AsyncConnection, *, as_of: datetime, threshold: float, min_jobs: int
) -> ResponseRateAlert | None:
    """Алерт, если итог (или пара) с ≥ `min_jobs` созревшими заявками ниже порога."""
    by_pair = await pair_liquidity(conn, Window(as_of - LOOKBACK, as_of), as_of=as_of)
    overall = by_pair.pop(None, None)
    low = {
        key: m.rr_4h
        for key, m in by_pair.items()
        if key is not None and _below(m.rr_4h, threshold, min_jobs)
    }
    if overall is None or not (_below(overall.rr_4h, threshold, min_jobs) or low):
        return None
    cities, categories = await pair_names(conn, low.keys())
    pairs = tuple(
        (f"{cities.get(city, city)} × {categories.get(category, category)}", ratio)
        for (city, category), ratio in sorted(low.items(), key=lambda item: item[1].hits)
    )
    return ResponseRateAlert(overall=overall.rr_4h, threshold=threshold, pairs=pairs)


async def send_alert(
    alert: ResponseRateAlert, *, sender: TelegramSender | None, chat_id: int | None
) -> None:
    log.warning(
        "response_rate_low",
        rate=alert.overall.value,
        jobs=alert.overall.total,
        threshold=alert.threshold,
        pairs=len(alert.pairs),
    )
    if sender is None or chat_id is None:
        # чата модераторов ещё нет (2.5b, K29): алерт должен дойти хоть куда-то
        sentry_sdk.capture_message("response rate@4h below threshold", level="warning")
        return
    await sender.send(OutgoingMessage(chat_id=chat_id, text=alert.text()))


@periodic("analytics.response_rate_alert", cron="5 7 * * *")
async def response_rate_alert(run: PeriodicRun) -> None:
    """Каждое утро (07:05 UTC — 08:05–09:05 по Белграду), к началу дежурства модераторов."""
    settings = await run.container.get(AnalyticsSettings)
    db = await run.container.get(DbSettings)
    as_of = datetime.fromtimestamp(run.timestamp, UTC)
    async with reporting_connection(db) as conn:
        alert = await check_response_rate(
            conn,
            as_of=as_of,
            threshold=settings.response_rate_alert_threshold,
            min_jobs=settings.response_rate_alert_min_jobs,
        )
    if alert is None:
        return
    chat_id = (await run.container.get(TelegramSettings)).moderators_chat_id
    # бот нужен, только если есть куда писать
    sender = await run.container.get(TelegramSender) if chat_id is not None else None
    await send_alert(alert, sender=sender, chat_id=chat_id)


def _below(ratio: Ratio, threshold: float, min_jobs: int) -> bool:
    return ratio.total >= min_jobs and (ratio.value or 0.0) < threshold


def _percent(ratio: Ratio) -> str:
    value = ratio.value
    shown = "—" if value is None else f"{value * 100:.0f}%"
    return f"{shown} ({ratio.hits}/{ratio.total})"
