"""Карточка заявки по подписке B1, подборка и напоминание о профиле (DEVELOPMENT_PLAN 5.7).

Каталоги — настоящие (backend/locales), часы — фейковые: «сегодня» и «завтра» считаются от
момента показа.
"""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.modules.notifications.domain.catalog import NotificationType
from app.modules.notifications.infrastructure.rendering import GettextNotificationRenderer
from app.platform.i18n.translator import Translator
from app.platform.kernel.localized import Locale
from app.platform.telegram.callbacks import CallbackAction, arg_ref, parse_callback
from app.platform.telegram.port import (
    AppButton,
    Button,
    ButtonLine,
    CallbackButton,
    InactiveButton,
)
from app.platform.testing.clock import FakeClock

pytestmark = pytest.mark.unit

MINI_APP = "https://app.test/"
JOB = UUID("01920000-0000-7000-8000-000000000001")
ALERT = UUID("01920000-0000-7000-8000-000000000002")
TEMPLATE = UUID("01920000-0000-7000-8000-000000000003")
LINK = "j_0Bd1u4lEy5iE5j9cQ0ZJqh"
SCRIPTS = (Locale.RU, Locale.SR_CYRL, Locale.SR_LATN)
UNITS = ("hour", "m2", "visit", "item", "lesson")
URGENCIES = ("asap", "today", "this_week", "flexible")
MATCHED = NotificationType.JOB_MATCHED
# 17:32 по Белграду 3 октября 2026 (UTC+2)
NOW = datetime(2026, 10, 3, 15, 32, tzinfo=UTC)

CARD = {
    "job_id": str(JOB),
    "alert_id": str(ALERT),
    "title": "Повесить люстру",
    "budget_type": "fixed",
    "budget_min": "500000",
    "budget_unit": "work",
    "urgency": "today",
    "from": "2026-10-03T16:00:00+00:00",
    "to": "2026-10-03T19:00:00+00:00",
    "district": "Лиман",
    "distance_m": "1200",
    "responses": "3",
    "max_responses": "5",
    "alert": "Мастер на час",
    "alert_more": "0",
    "template_0": str(TEMPLATE),
    "template_0_title": "Могу сегодня",
}


@pytest.fixture(scope="module")
def renderer() -> GettextNotificationRenderer:
    clock = FakeClock()
    clock.set(NOW)
    return GettextNotificationRenderer(Translator.load(), MINI_APP, clock)


def rows(lines: tuple[ButtonLine, ...]) -> list[list[Button]]:
    return [list(line) if isinstance(line, tuple) else [line] for line in lines]


def test_card_matches_the_artboard(renderer: GettextNotificationRenderer) -> None:
    """B1: заголовок, название жирным с бюджетом, район с расстоянием и время, места и
    подписка — как на артборде."""
    text, _ = renderer.telegram(MATCHED, CARD, LINK, Locale.RU)

    assert text == (
        "<b>Новая заявка рядом</b>\n"
        "<b>Повесить люстру</b> · 5 000 RSD\n"
        "Лиман, ≈ 1,2 км · сегодня 18:00–21:00\n"
        "Откликов 3 из 5 · подписка «Мастер на час»"
    )


def test_card_buttons_open_respond_hide_and_pause(renderer: GettextNotificationRenderer) -> None:
    _, buttons = renderer.telegram(MATCHED, CARD, LINK, Locale.RU)

    [[open_job], [template], [hide, pause]] = rows(buttons)
    assert isinstance(open_job, AppButton)
    assert (open_job.text, open_job.url) == ("Открыть заявку", f"{MINI_APP}?startapp={LINK}")
    assert isinstance(template, CallbackButton)
    assert template.text == "Откликнуться шаблоном «Могу сегодня»"
    respond = parse_callback(template.data)
    assert respond is not None
    assert (respond.action, respond.id, arg_ref(respond.arg)) == (
        CallbackAction.JOB_RESPOND,
        JOB,
        TEMPLATE,
    )
    assert isinstance(hide, CallbackButton)
    assert isinstance(pause, CallbackButton)
    assert (hide.text, pause.text) == ("Не подходит", "Пауза подписки")
    hidden, paused = parse_callback(hide.data), parse_callback(pause.data)
    assert hidden is not None
    assert paused is not None
    assert (hidden.action, hidden.id) == (CallbackAction.JOB_HIDE, JOB)
    assert (paused.action, paused.id) == (CallbackAction.ALERT_PAUSE, ALERT)
    assert all(len(button.data.encode()) <= 64 for button in (template, hide, pause))


def test_card_variants(renderer: GettextNotificationRenderer) -> None:
    """Диапазон с единицей, договорная, завтра и без времени, подписка по районам, «и ещё»."""
    card = {
        **CARD,
        "budget_type": "range",
        "budget_min": "300000",
        "budget_max": "500000",
        "budget_unit": "hour",
        "from": "2026-10-04T08:00:00+00:00",
        "alert_more": "2",
    }
    del card["to"]
    del card["distance_m"]
    text = renderer.text(MATCHED, card, Locale.RU)

    assert text.title == "Новая заявка по подписке"
    assert text.body == (
        "Повесить люстру · 3 000–5 000 RSD в час\n"
        "Лиман · завтра 10:00\n"
        "Откликов 3 из 5 · подписка «Мастер на час» и ещё 2"
    )
    urgent = {**CARD, "budget_type": "negotiable", "urgency": "asap", "distance_m": "800"}
    del urgent["budget_min"], urgent["from"], urgent["to"]
    assert renderer.text(MATCHED, urgent, Locale.RU).body.splitlines()[:2] == [
        "Повесить люстру · Договорная",
        "Лиман, ≈ 800 м · срочно",
    ]
    later = {**CARD, "from": "2026-10-12T08:00:00+00:00"}
    del later["to"]
    assert "12 окт. 10:00" in renderer.text(MATCHED, later, Locale.RU).body


def test_card_title_and_name_are_escaped(renderer: GettextNotificationRenderer) -> None:
    text, _ = renderer.telegram(
        MATCHED, {**CARD, "title": "<b>Кран</b> & мойка", "alert": "A&B"}, LINK, Locale.RU
    )

    assert "<b>&lt;b&gt;Кран&lt;/b&gt; &amp; мойка</b>" in text
    assert "«A&amp;B»" in text


def test_card_without_templates_still_has_hide_and_pause(
    renderer: GettextNotificationRenderer,
) -> None:
    card = {key: value for key, value in CARD.items() if not key.startswith("template_")}

    _, buttons = renderer.telegram(MATCHED, card, LINK, Locale.RU)

    assert [[button.text for button in row] for row in rows(buttons)] == [
        ["Открыть заявку"],
        ["Не подходит", "Пауза подписки"],
    ]


def test_closed_job_card_keeps_open_and_disables_the_rest(
    renderer: GettextNotificationRenderer,
) -> None:
    open_job, closed = renderer.retired_buttons(MATCHED, CARD, LINK, Locale.RU)

    assert isinstance(open_job, AppButton)
    assert open_job.text == "Открыть заявку"
    assert closed == InactiveButton(text="Приём откликов закрыт")


@pytest.mark.parametrize("locale", SCRIPTS)
def test_alert_texts_on_three_scripts(
    renderer: GettextNotificationRenderer, locale: Locale
) -> None:
    cases: list[tuple[NotificationType, dict[str, str]]] = [
        (MATCHED, CARD),
        (MATCHED, {**CARD, "budget_type": "negotiable", "urgency": "flexible", "alert_more": "1"}),
        (NotificationType.JOB_DIGEST, {"alert_0": "Уборка", "alert_0_count": "2"}),
        (
            NotificationType.JOB_DIGEST,
            {"alert_0": "Уборка", "alert_0_count": "2", "alert_1": "Ремонт", "alert_1_count": "3"},
        ),
        (NotificationType.PROFILE_STALE_REMINDER, {}),
    ]
    no_time = {key: value for key, value in CARD.items() if key not in {"from", "to"}}
    cases += [(MATCHED, {**CARD, "budget_unit": unit}) for unit in UNITS]
    cases += [(MATCHED, {**no_time, "urgency": urgency}) for urgency in URGENCIES]
    for type_, params in cases:
        text, buttons = renderer.telegram(type_, params, LINK, locale)
        assert "notifications." not in text, (type_, params)
        labels = [button.text for row in rows(buttons) for button in row]
        assert [label for label in labels if "notifications." in label] == []
    [_, closed] = renderer.retired_buttons(MATCHED, CARD, LINK, locale)
    assert isinstance(closed, InactiveButton)
    assert "notifications." not in closed.text


def test_digest_one_alert_and_several(renderer: GettextNotificationRenderer) -> None:
    one = renderer.text(
        NotificationType.JOB_DIGEST, {"alert_0": "Сборка мебели", "alert_0_count": "2"}, Locale.RU
    )
    assert (one.title, one.body) == (
        "Подборка заявок",
        "Новые заявки по подписке «Сборка мебели»: 2.",
    )
    many = renderer.text(
        NotificationType.JOB_DIGEST,
        {"alert_0": "Уборка", "alert_0_count": "2", "alert_1": "Ремонт", "alert_1_count": "3"},
        Locale.RU,
    )
    assert many.body == "Новые заявки по подпискам: 5.\n• «Уборка» — 2\n• «Ремонт» — 3"
    _, [button] = renderer.telegram(
        NotificationType.JOB_DIGEST,
        {"alert_0": "Уборка", "alert_0_count": "1"},
        "m_feed",
        Locale.RU,
    )
    assert isinstance(button, AppButton)
    assert (button.text, button.url) == ("Открыть ленту", f"{MINI_APP}?startapp=m_feed")


def test_stale_profile_reminder_leads_to_availability_and_cabinet(
    renderer: GettextNotificationRenderer,
) -> None:
    text, buttons = renderer.telegram(
        NotificationType.PROFILE_STALE_REMINDER, {}, "m_availability", Locale.RU
    )

    assert text.startswith("<b>Клиенты ищут специалистов</b>\n")
    assert [(b.text, b.url) for b in buttons if isinstance(b, AppButton)] == [
        ("Включить «Доступен сегодня»", f"{MINI_APP}?startapp=m_availability"),
        ("Обновить профиль", f"{MINI_APP}?startapp=m_profile"),
    ]
