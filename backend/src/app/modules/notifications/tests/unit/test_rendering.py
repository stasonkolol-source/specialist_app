"""Тексты уведомлений на трёх письменностях (DEVELOPMENT_PLAN 2.3a, ADR-0013).

Каталоги — настоящие (backend/locales): ключ, которого нет, вылез бы в текст как есть.
"""

from collections.abc import Mapping
from typing import cast
from uuid import UUID

import pytest

from app.modules.notifications.domain.catalog import NotificationType
from app.modules.notifications.infrastructure.rendering import RENDERED, GettextNotificationRenderer
from app.platform.contracts.events.identity import RestrictionKind
from app.platform.i18n.catalogs import LOCALES_DIR
from app.platform.i18n.translator import Translator
from app.platform.kernel.localized import Locale
from app.platform.telegram.callbacks import (
    CallbackAction,
    CallbackData,
    arg_ref,
    parse_callback,
    ref_arg,
)
from app.platform.telegram.deeplinks import (
    LinkSection,
    LinkType,
    StartLink,
    encode_start_param,
    parse_start_param,
)
from app.platform.telegram.port import AppButton, Button, ButtonLine, CallbackButton

pytestmark = pytest.mark.unit

SCRIPTS = (Locale.RU, Locale.SR_CYRL, Locale.SR_LATN)


def flat(lines: tuple[ButtonLine, ...]) -> list[Button]:
    """Кнопки всех рядов клавиатуры по порядку."""
    return [button for line in lines for button in (line if isinstance(line, tuple) else (line,))]


MINI_APP = "https://app.test/"
RESTRICTED = NotificationType.ACCOUNT_RESTRICTED
DECISION = NotificationType.MODERATION_DECISION


@pytest.fixture(scope="module")
def renderer() -> GettextNotificationRenderer:
    return GettextNotificationRenderer(Translator.load(), MINI_APP)


def full_text(
    renderer: GettextNotificationRenderer,
    type_: NotificationType,
    params: Mapping[str, str],
    locale: Locale,
) -> str:
    text = renderer.text(type_, params, locale)
    return f"{text.title}\n{text.body}"


def test_restriction_until_a_date_on_three_scripts(renderer: GettextNotificationRenderer) -> None:
    params = {"kind": "posting_blocked", "until": "2026-10-12T06:30:00+00:00"}  # 08:30 Белград

    texts = {locale: full_text(renderer, RESTRICTED, params, locale) for locale in SCRIPTS}

    assert texts[Locale.RU] == (
        "Аккаунт ограничен\nПубликовать заявки и профиль пока нельзя."
        " Ограничение действует до 12 октября 2026 г., 08:30."
        " Подробности — в правилах площадки."
    )
    # после «do» сербский месяц — в родительном: «do 12. oktobra», не «do 12. oktobar»
    assert "до 12. октобра 2026. 08:30." in texts[Locale.SR_CYRL]
    assert texts[Locale.SR_LATN].startswith("Nalog je ograničen\n")
    assert "do 12. oktobra 2026. 08:30." in texts[Locale.SR_LATN]


def test_serbian_deadline_and_reminder_dates_are_genitive(
    renderer: GettextNotificationRenderer,
) -> None:
    dispute = renderer.text(
        NotificationType.DISPUTE_OPENED,
        {"title": "Люстра", "by": "performer", "kind": "no_show", "until": "2026-10-07T08:00:00Z"},
        Locale.SR_LATN,
    )
    assert "Odgovorite do 7. oktobra 2026. 10:00 —" in dispute.body
    # напоминание «„…“ — когда»: дата в значении «когда» — тоже родительный
    reminder = renderer.text(
        NotificationType.DEAL_REMINDER,
        {"title": "Люстра", "at": "2026-10-03T17:00:00+00:00"},
        Locale.SR_CYRL,
    )
    assert reminder.body.endswith("3. октобра 2026. 19:00.")


@pytest.mark.parametrize(
    "kind",
    # теневой бан не сообщается (notify_account_restricted)
    [kind.value for kind in RestrictionKind if kind is not RestrictionKind.SHADOW_BANNED],
)
@pytest.mark.parametrize("locale", SCRIPTS)
def test_every_restriction_has_its_own_words(
    renderer: GettextNotificationRenderer, kind: str, locale: Locale
) -> None:
    text = full_text(renderer, RESTRICTED, {"kind": kind}, locale)

    assert "notifications." not in text  # ключ без перевода вылез бы как есть
    assert "{" not in text


def test_ban_is_called_a_ban(renderer: GettextNotificationRenderer) -> None:
    text = renderer.text(RESTRICTED, {"kind": "banned"}, Locale.RU)

    assert text.title == "Аккаунт заблокирован"
    assert "до " not in text.body  # бессрочно — без даты


@pytest.mark.parametrize("locale", SCRIPTS)
@pytest.mark.parametrize(
    ("entity", "code"),
    [
        ("job", "contact_leak"),
        ("profile", "spam_ad"),
        ("response", "prepayment_scam"),
        ("review", "off_platform_payment"),
        ("message", "mule_recruitment"),
        ("media", "weapons"),
        ("job", "not_a_service_request"),
        ("job", "vacancy"),
        ("user", "brand_new_code"),  # неизвестные вид и код — общие слова, а не ключ
    ],
)
def test_moderation_decision_names_the_content_and_the_reason(
    renderer: GettextNotificationRenderer, locale: Locale, entity: str, code: str
) -> None:
    text = full_text(renderer, DECISION, {"entity_type": entity, "decision_code": code}, locale)

    assert "notifications." not in text
    assert "{" not in text


def test_decision_says_who_decided_and_warns(renderer: GettextNotificationRenderer) -> None:
    params = {"entity_type": "job", "decision_code": "contact_leak"}

    automated = renderer.text(DECISION, params | {"automated": "true"}, Locale.RU).body
    warned = renderer.text(
        DECISION, params | {"automated": "false", "sanction": "warning"}, Locale.RU
    ).body
    struck = renderer.text(DECISION, params | {"sanction": "strike_1"}, Locale.RU).body

    assert automated.endswith("Исправьте и отправьте снова. Решение принято автоматически.")
    assert warned.endswith(
        "Это предупреждение: при повторных нарушениях аккаунт ограничат. Решение принял модератор."
    )
    assert struck.endswith("Исправьте и отправьте снова.")  # об ограничении — account.restricted


def test_prohibited_labels_share_one_reason(renderer: GettextNotificationRenderer) -> None:
    bodies = {
        renderer.text(DECISION, {"entity_type": "job", "decision_code": code}, Locale.RU).body
        for code in ("drug_courier", "sexual_services", "weapons")
    }

    assert bodies == {"Причина: запрещённые товары или услуги. Исправьте и отправьте снова."}


def test_bot_message_is_escaped_html_with_a_mini_app_button(
    renderer: GettextNotificationRenderer,
) -> None:
    text, buttons = renderer.telegram(
        DECISION, {"entity_type": "job", "decision_code": "<b>x</b>"}, "l_terms", Locale.RU
    )

    assert text.startswith("<b>Заявку нужно исправить</b>\n")  # статус S23 — «Нужно исправить"
    assert "<b>x</b>" not in text  # неизвестный код — общие слова; разметку он не вносит
    [button] = buttons
    assert isinstance(button, AppButton)
    assert button.text == "Исправить"
    assert button.url == f"{MINI_APP}?startapp=l_terms"
    assert parse_start_param("l_terms") is not None


def test_appeal_outcome_on_three_scripts(renderer: GettextNotificationRenderer) -> None:
    """Итог апелляции (2.5b) — тот же тип `moderation.decision`: санкция снята или решение в
    силе с причиной; кнопка — открыть приложение, а не «Исправить»."""
    granted = {"entity_type": "appeal", "appeal": "granted", "decision_code": "other"}
    denied = {"entity_type": "appeal", "appeal": "denied", "decision_code": "decision_upheld"}

    assert full_text(renderer, DECISION, granted, Locale.RU) == (
        "Апелляция удовлетворена\n"
        "Модератор пересмотрел решение: ограничение снято. Спасибо, что написали."
    )
    assert full_text(renderer, DECISION, denied, Locale.RU) == (
        "Решение осталось в силе\n"
        "Модератор пересмотрел решение и оставил его: нарушение подтвердилось. Это окончательный"
        " ответ."
    )
    assert full_text(renderer, DECISION, denied, Locale.SR_LATN).startswith(
        "Odluka ostaje na snazi\n"
    )
    _, [button] = renderer.telegram(DECISION, granted, "home", Locale.RU)
    assert isinstance(button, AppButton)
    assert button.text == "Открыть «Соседи»"


def test_text_is_escaped_so_only_the_title_is_markup() -> None:
    translator = Translator(
        {
            Locale.RU: {
                "notifications.account_restricted.title.restricted": "A & <B>",
                "notifications.account_restricted.body.suspended": "1 < 2",
                "notifications.account_restricted.rules": "",
            }
        }
    )

    text, _ = GettextNotificationRenderer(translator, None).telegram(
        RESTRICTED, {"kind": "suspended"}, None, Locale.RU
    )

    assert text.startswith("<b>A &amp; &lt;B&gt;</b>\n1 &lt; 2")


def test_without_mini_app_address_there_are_no_buttons() -> None:
    renderer = GettextNotificationRenderer(Translator.load(), None)

    _, buttons = renderer.telegram(RESTRICTED, {"kind": "suspended"}, "l_terms", Locale.RU)

    assert buttons == ()


def test_every_catalog_type_has_templates() -> None:
    """С подписками (5.7) шаблоны есть у всех типов каталога: Notify не создаст уведомление без
    текста (renders), а новый тип получит шаблоны вместе со своим подписчиком."""
    assert set(RENDERED) == set(NotificationType)


@pytest.mark.parametrize("locale", SCRIPTS)
def test_channel_check_message_on_three_scripts(
    renderer: GettextNotificationRenderer, locale: Locale
) -> None:
    text, [button] = renderer.telegram(NotificationType.SYSTEM_TEST, {}, "h", locale)

    assert "notifications." not in text
    assert isinstance(button, AppButton)
    assert button.url == f"{MINI_APP}?startapp=h"


@pytest.mark.parametrize("locale", SCRIPTS)
def test_profile_published_says_so_with_a_button(
    renderer: GettextNotificationRenderer, locale: Locale
) -> None:
    text = full_text(renderer, NotificationType.PROFILE_PUBLISHED, {}, locale)
    _, buttons = renderer.telegram(NotificationType.PROFILE_PUBLISHED, {}, "s_abc", locale)

    assert "notifications." not in text
    # профиль — и сразу подписка на заявки: она приводит заявки новому специалисту (UX №9)
    assert all(isinstance(button, AppButton) for button in buttons)
    opened, alerts = (cast(AppButton, button) for button in buttons)
    assert alerts.url == f"{MINI_APP}?startapp=m_alerts"
    assert "notifications." not in opened.text
    assert "notifications." not in alerts.text


JOB_ID = UUID("01a0fc88-f156-726a-9a76-99e3d10e5542")


def job_params(*, can_extend: bool, title: str = "Повесить люстру") -> dict[str, str]:
    return {"job_id": str(JOB_ID), "title": title, "can_extend": "true" if can_extend else "false"}


def callbacks(buttons: tuple[object, ...]) -> list[tuple[str, CallbackData | None]]:
    return [(b.text, parse_callback(b.data)) for b in buttons if isinstance(b, CallbackButton)]


JOB_LINK = encode_start_param(StartLink(type=LinkType.JOB, id=JOB_ID))


def opens(buttons: tuple[ButtonLine, ...]) -> list[tuple[str, str]]:
    """Кнопки Mini App: подпись и адрес."""
    return [(b.text, b.url) for b in flat(buttons) if isinstance(b, AppButton)]


def test_expiring_job_offers_extend_and_close_as_found(
    renderer: GettextNotificationRenderer,
) -> None:
    text, buttons = renderer.telegram(
        NotificationType.JOB_EXPIRING, job_params(can_extend=True), JOB_LINK, Locale.RU
    )

    assert text == (
        "<b>Срок заявки скоро истечёт</b>\nСрок заявки «Повесить люстру» истечёт через 2 часа."
        " Если исполнитель ещё нужен — продлите заявку."
    )
    assert callbacks(buttons) == [
        ("Продлить", CallbackData(CallbackAction.JOB_EXTEND, JOB_ID)),
        ("Закрыть: исполнитель найден", CallbackData(CallbackAction.JOB_CLOSE, JOB_ID, "found")),
    ]
    # №11: решить, продлевать ли, — глядя на заявку и отклики (S23)
    assert opens(buttons) == [("Открыть заявку", f"{MINI_APP}?startapp={JOB_LINK}")]


def test_expired_job_after_three_extensions_can_only_be_closed(
    renderer: GettextNotificationRenderer,
) -> None:
    text, buttons = renderer.telegram(
        NotificationType.JOB_EXPIRED, job_params(can_extend=False), JOB_LINK, Locale.RU
    )

    assert text.startswith("<b>Срок заявки истёк</b>\n")  # статус — «Срок истёк — продлите»
    assert "Продлевать её больше нельзя" in text
    assert callbacks(buttons) == [("Закрыть", CallbackData(CallbackAction.JOB_CLOSE, JOB_ID))]
    assert opens(buttons) == [("Открыть заявку", f"{MINI_APP}?startapp={JOB_LINK}")]


@pytest.mark.parametrize("locale", SCRIPTS)
@pytest.mark.parametrize("type_", [NotificationType.JOB_EXPIRING, NotificationType.JOB_EXPIRED])
def test_job_term_texts_on_three_scripts(
    renderer: GettextNotificationRenderer, type_: NotificationType, locale: Locale
) -> None:
    for can_extend in (True, False):
        text, buttons = renderer.telegram(type_, job_params(can_extend=can_extend), None, locale)
        assert "notifications." not in text
        assert all("notifications." not in b.text for b in flat(buttons))


def test_long_title_is_shortened_and_markup_escaped(renderer: GettextNotificationRenderer) -> None:
    title = "<b>Люстра</b> " + "очень " * 20

    text, _ = renderer.telegram(
        NotificationType.JOB_EXPIRED, job_params(can_extend=True, title=title), None, Locale.RU
    )

    assert "&lt;b&gt;Люстра&lt;/b&gt;" in text
    assert "…»" in text


def test_job_term_without_a_job_id_has_no_buttons(renderer: GettextNotificationRenderer) -> None:
    _, buttons = renderer.telegram(
        NotificationType.JOB_EXPIRING, {"title": "x", "can_extend": "true"}, None, Locale.RU
    )

    assert buttons == ()


def test_new_responses_message_counts_them_and_leads_to_the_job(
    renderer: GettextNotificationRenderer,
) -> None:
    link = encode_start_param(StartLink(type=LinkType.JOB, id=JOB_ID))
    one, buttons = renderer.telegram(
        NotificationType.RESPONSE_RECEIVED,
        {"title": "Повесить люстру", "count": "1"},
        link,
        Locale.RU,
    )
    three, _ = renderer.telegram(
        NotificationType.RESPONSE_RECEIVED,
        {"title": "Повесить люстру", "count": "3"},
        "j_abc",
        Locale.RU,
    )

    assert one.startswith("<b>Новые отклики</b>\nНовый отклик на заявку «Повесить люстру».")
    assert "Новых откликов: 3 — на заявку «Повесить люстру»." in three
    [button] = buttons
    assert isinstance(button, AppButton)
    assert button.text == "Посмотреть отклики"
    assert button.url == f"{MINI_APP}?startapp={link}"


@pytest.mark.parametrize("locale", SCRIPTS)
def test_new_responses_texts_on_three_scripts(
    renderer: GettextNotificationRenderer, locale: Locale
) -> None:
    for count in ("1", "4"):
        text, buttons = renderer.telegram(
            NotificationType.RESPONSE_RECEIVED, {"title": "x", "count": count}, "j_abc", locale
        )
        assert "notifications." not in text
        assert all("notifications." not in b.text for b in flat(buttons))


TEMPLATE_ID = UUID("01a0fc88-f156-726a-9a76-99e3d10e5543")


def invite_params(*, direct: bool, templates: int = 1) -> dict[str, str]:
    params = {
        "job_id": str(JOB_ID),
        "title": "Повесить люстру",
        "client": "Елена К.",
        "direct": "true" if direct else "false",
    }
    if templates:
        params |= {"template_0": str(TEMPLATE_ID), "template_0_title": "Могу сегодня"}
    return params


def test_invitation_leads_to_the_job_and_responds_with_a_template(
    renderer: GettextNotificationRenderer,
) -> None:
    link = encode_start_param(StartLink(type=LinkType.JOB, id=JOB_ID))

    text, buttons = renderer.telegram(
        NotificationType.JOB_INVITED, invite_params(direct=False), link, Locale.RU
    )

    assert text == (
        "<b>Вас приглашают откликнуться</b>\n"
        "Елена К. приглашает вас откликнуться на заявку «Повесить люстру»."
    )
    app, template = buttons
    assert isinstance(app, AppButton)
    assert (app.text, app.url) == ("Посмотреть заявку", f"{MINI_APP}?startapp={link}")
    assert isinstance(template, CallbackButton)
    assert template.text == "Откликнуться: «Могу сегодня»"
    data = parse_callback(template.data)
    assert data == CallbackData(CallbackAction.JOB_RESPOND, JOB_ID, ref_arg(TEMPLATE_ID))
    assert arg_ref(data.arg) == TEMPLATE_ID


def test_direct_request_says_only_you_see_it(renderer: GettextNotificationRenderer) -> None:
    text, buttons = renderer.telegram(
        NotificationType.JOB_INVITED,
        invite_params(direct=True, templates=0) | {"client": ""},
        "j_abc",
        Locale.RU,
    )

    assert text.startswith("<b>Прямой запрос</b>\nКлиент просит именно вас: «Повесить люстру».")
    assert [b.text for b in flat(buttons)] == ["Посмотреть заявку"]


@pytest.mark.parametrize("locale", SCRIPTS)
def test_invitation_texts_on_three_scripts(
    renderer: GettextNotificationRenderer, locale: Locale
) -> None:
    for direct in (True, False):
        text, buttons = renderer.telegram(
            NotificationType.JOB_INVITED, invite_params(direct=direct, templates=1), "j_x", locale
        )
        assert "notifications." not in text
        assert all("notifications." not in b.text for b in flat(buttons))
        assert len(buttons) == 2


# --- сделки (6.1b) -------------------------------------------------------------------------

DEAL_ID = UUID("0192f5a8-7c3e-7b21-9d4f-3a6b8c1e2f47")
DEAL_LINK = encode_start_param(StartLink(type=LinkType.DEAL, id=DEAL_ID))
CHAT_LINK = encode_start_param(StartLink(type=LinkType.CHAT, id=DEAL_ID))


def test_accepted_performer_is_led_to_the_deal(renderer: GettextNotificationRenderer) -> None:
    text, [button] = renderer.telegram(
        NotificationType.RESPONSE_ACCEPTED, {"title": "Повесить люстру"}, DEAL_LINK, Locale.RU
    )

    assert text == "<b>Вас выбрали</b>\nЗаявка «Повесить люстру». Адрес и время — в сделке."
    assert isinstance(button, AppButton)
    assert (button.text, button.url) == ("Открыть сделку", f"{MINI_APP}?startapp={DEAL_LINK}")


RESPONSES_LINK = encode_start_param(StartLink(type=LinkType.MINE, section=LinkSection.RESPONSES))


@pytest.mark.parametrize(
    ("locale", "text", "button"),
    [
        (
            Locale.RU,
            "<b>Выбрали другого исполнителя</b>\nЗаявка «Люстра». Спасибо за отклик — в ленте"
            " есть другие заявки рядом.",
            "Мои отклики",
        ),
        (
            Locale.SR_LATN,
            "<b>Izabran je drugi izvođač</b>\nZahtev „Lustra“. Hvala na ponudi — u listi ima"
            " drugih zahteva u blizini.",
            "Moje ponude",
        ),
        (
            Locale.SR_CYRL,
            "<b>Изабран је други извођач</b>\nЗахтев „Люстра“. Хвала на понуди — у листи има"
            " других захтева у близини.",
            "Моје понуде",
        ),
    ],
)
def test_passed_over_performer_is_led_to_my_responses(
    renderer: GettextNotificationRenderer, locale: Locale, text: str, button: str
) -> None:
    """№11: заголовок — слово статуса S17 («Выбрали другого»), кнопка — к отклику в «Моих
    откликах»: чужую заявку после выбора исполнителю не открыть."""
    title = "Lustra" if locale is Locale.SR_LATN else "Люстра"
    rendered, buttons = renderer.telegram(
        NotificationType.RESPONSE_NOT_SELECTED, {"title": title}, RESPONSES_LINK, locale
    )

    assert rendered == text
    assert opens(buttons) == [(button, f"{MINI_APP}?startapp=m_responses")]


@pytest.mark.parametrize(
    ("locale", "text"),
    [
        (
            Locale.RU,
            "<b>Заявка закрыта без выбора</b>\nЗаявка «Люстра». Спасибо за отклик — в ленте"
            " есть другие заявки рядом.",
        ),
        (
            Locale.SR_LATN,
            "<b>Zahtev je zatvoren bez izbora</b>\nZahtev „Lustra“. Hvala na ponudi — u listi"
            " ima drugih zahteva u blizini.",
        ),
        (
            Locale.SR_CYRL,
            "<b>Захтев је затворен без избора</b>\nЗахтев „Люстра“. Хвала на понуди — у листи"
            " има других захтева у близини.",
        ),
    ],
)
def test_closed_job_is_not_called_another_choice(
    renderer: GettextNotificationRenderer, locale: Locale, text: str
) -> None:
    """MU-11: клиент закрыл или удалил заявку — «Заявка закрыта без выбора» (слово статуса S17),
    не «выбрал другого»; кнопка — «Мои отклики»."""
    title = "Lustra" if locale is Locale.SR_LATN else "Люстра"
    rendered, buttons = renderer.telegram(
        NotificationType.RESPONSE_NOT_SELECTED,
        {"title": title, "reason": "job_closed"},
        RESPONSES_LINK,
        locale,
    )

    assert rendered == text
    assert [url for _, url in opens(buttons)] == [f"{MINI_APP}?startapp=m_responses"]


@pytest.mark.parametrize(
    ("params", "body"),
    [
        (
            {"by": "performer", "reason": "plans_changed", "reopened": "true"},
            "Исполнитель отменил сделку «Люстра»: планы изменились. Заявка снова открыта,"
            " прежние отклики вернулись.",
        ),
        (
            {"by": "client", "reason": "no_contact", "reopened": "false"},
            "Клиент отменил сделку «Люстра»: нет связи.",
        ),
        (
            {"by": "system", "reason": "expired", "reopened": "false"},
            "Предложение «Люстра» истекло: ответа не было 3 дня.",
        ),
        (
            {"by": "system", "reason": "account_deleted", "reopened": "true"},
            "Сделка «Люстра» отменена: аккаунт второй стороны удалён. Заявка снова открыта,"
            " прежние отклики вернулись.",
        ),
    ],
    ids=["by-performer", "by-client", "expired", "account-deleted"],
)
def test_cancelled_deal_says_who_and_why(
    renderer: GettextNotificationRenderer, params: dict[str, str], body: str
) -> None:
    text = renderer.text(NotificationType.DEAL_CANCELLED, {"title": "Люстра", **params}, Locale.RU)

    assert (text.title, text.body) == ("Сделка отменена", body)


@pytest.mark.parametrize(
    ("by", "first"),
    [
        ("client", "Клиент предлагает договориться: «Люстра»."),
        ("performer", "Исполнитель предлагает договориться: «Люстра»."),
    ],
)
def test_proposal_shows_terms_with_confirm_and_decline(
    renderer: GettextNotificationRenderer, by: str, first: str
) -> None:
    params = {
        "title": "Люстра",
        "by": by,
        "deal_id": str(DEAL_ID),
        "at": "2026-10-03T17:00:00+00:00",
        "price_type": "fixed",
        "price": "350000",
    }

    text, [confirm, decline, terms] = renderer.telegram(
        NotificationType.DEAL_PROPOSED, params, DEAL_LINK, Locale.RU
    )

    title, *lines = text.split("\n")
    assert (title, lines[0]) == ("<b>Договорились?</b>", first)
    assert lines[1].startswith("Когда: 3 октября 2026")
    assert "19:00" in lines[1]  # Белград
    assert lines[2:] == ["Цена: 3\u00a0500 RSD.", "Подтвердите или отклоните в течение 3 дней."]
    assert isinstance(confirm, CallbackButton)
    assert isinstance(decline, CallbackButton)
    assert (confirm.text, decline.text) == ("Подтвердить", "Отклонить")
    assert parse_callback(confirm.data) == CallbackData(CallbackAction.DEAL_CONFIRM, DEAL_ID)
    assert parse_callback(decline.data) == CallbackData(CallbackAction.DEAL_DECLINE, DEAL_ID)
    assert isinstance(terms, AppButton)
    assert (terms.text, terms.url) == ("Посмотреть условия", f"{MINI_APP}?startapp={DEAL_LINK}")


@pytest.mark.parametrize(
    ("locale", "price_type", "price", "line"),
    [
        (Locale.RU, "from", "350050", "Цена: от 3\u00a0500,50 RSD."),
        (Locale.RU, "hourly", "120000", "Цена: 1\u00a0200 RSD в час."),
        (Locale.RU, "negotiable", None, "Цена: договорная."),
        (Locale.SR_CYRL, "fixed", "1250000", "Цена: 12.500 RSD."),
        (Locale.SR_LATN, "negotiable", None, "Cena: po dogovoru."),
    ],
)
def test_proposal_price_in_words_of_the_language(
    renderer: GettextNotificationRenderer,
    locale: Locale,
    price_type: str,
    price: str | None,
    line: str,
) -> None:
    params = {"title": "Люстра", "by": "client", "price_type": price_type}
    if price is not None:
        params["price"] = price

    text = renderer.text(NotificationType.DEAL_PROPOSED, params, locale)

    assert line in text.body.split("\n")


def test_proposal_without_terms_is_just_the_title(renderer: GettextNotificationRenderer) -> None:
    text = renderer.text(
        NotificationType.DEAL_PROPOSED, {"title": "Люстра", "by": "performer"}, Locale.RU
    )

    assert text.body == (
        "Исполнитель предлагает договориться: «Люстра».\n"
        "Подтвердите или отклоните в течение 3 дней."
    )


@pytest.mark.parametrize(
    ("params", "title", "body"),
    [
        (
            {"name": "Алексей", "count": "1", "preview": "Буду в 19:00"},
            "Алексей пишет",
            "«Буду в 19:00»",
        ),
        (
            {"name": "Алексей", "count": "3", "preview": "Буду в 19:00"},
            "Алексей пишет",
            "«Буду в 19:00»\nНовых сообщений: 3.",
        ),
        ({"name": "", "count": "2"}, "Собеседник пишет", "Новых сообщений: 2."),
    ],
    ids=["one", "several", "no-text"],
)
def test_message_notice_says_who_and_what_with_a_reply_button(
    renderer: GettextNotificationRenderer, params: dict[str, str], title: str, body: str
) -> None:
    text, [button] = renderer.telegram(
        NotificationType.MESSAGE_RECEIVED, params, CHAT_LINK, Locale.RU
    )

    assert text == f"<b>{title}</b>\n{body}"
    assert isinstance(button, AppButton)
    assert (button.text, button.url) == ("Ответить", f"{MINI_APP}?startapp={CHAT_LINK}")


@pytest.mark.parametrize("locale", SCRIPTS)
def test_message_notice_on_three_scripts(
    renderer: GettextNotificationRenderer, locale: Locale
) -> None:
    text, buttons = renderer.telegram(
        NotificationType.MESSAGE_RECEIVED,
        {"name": "Ana", "count": "2", "preview": "Dobar dan"},
        CHAT_LINK,
        locale,
    )

    assert "notifications." not in text
    assert all("notifications." not in b.text for b in flat(buttons))


def test_reminder_names_the_time(renderer: GettextNotificationRenderer) -> None:
    text = renderer.text(
        NotificationType.DEAL_REMINDER,
        {"title": "Люстра", "at": "2026-10-03T17:00:00+00:00"},
        Locale.RU,
    )

    assert text.title == "Скоро работа"
    assert text.body.startswith("«Люстра» — 3 октября 2026")
    assert "19:00" in text.body  # Белград


def test_completion_prompt_has_yes_and_problem_in_one_row(
    renderer: GettextNotificationRenderer,
) -> None:
    text, [row] = renderer.telegram(
        NotificationType.DEAL_COMPLETION_PROMPT,
        {"title": "Люстра", "deal_id": str(DEAL_ID)},
        DEAL_LINK,
        Locale.RU,
    )
    assert isinstance(row, tuple)
    yes, problem = row

    assert text.startswith("<b>Работа выполнена?</b>")
    assert isinstance(yes, CallbackButton)
    assert yes.text == "Да, всё хорошо"
    assert parse_callback(yes.data) == CallbackData(CallbackAction.DEAL_COMPLETE, DEAL_ID)
    assert isinstance(problem, AppButton)
    # «Есть проблема» — сразу спор S52 (`p_`, 6.1c), не карточка сделки
    assert (problem.text, problem.url) == ("Есть проблема", f"{MINI_APP}?startapp={DISPUTE_LINK}")


@pytest.mark.parametrize(
    ("by", "name", "body"),
    [
        (
            "performer",
            "Алексей Морозов",
            "Алексей Морозов: работа «Люстра» выполнена. Всё в порядке?",
        ),
        ("client", "Ирина", "Ирина: работа «Люстра» выполнена. Всё в порядке?"),
        # аккаунт удалён или уведомление создано до имени в параметрах — роль вместо имени
        ("performer", "", "Исполнитель: работа «Люстра» выполнена. Всё в порядке?"),
        ("client", None, "Клиент: работа «Люстра» выполнена. Всё в порядке?"),
    ],
)
def test_completion_prompt_names_who_marked_it(
    renderer: GettextNotificationRenderer, by: str, name: str | None, body: str
) -> None:
    params = {"title": "Люстра", "by": by} | ({"name": name} if name is not None else {})

    text = renderer.text(NotificationType.DEAL_COMPLETION_PROMPT, params, Locale.RU)

    assert (text.title, text.body) == ("Работа выполнена?", body)


def test_completion_prompt_name_is_text_not_markup(renderer: GettextNotificationRenderer) -> None:
    params = {
        "title": "Люстра",
        "by": "performer",
        "name": "<b>Ana</b> & Co",
        "deal_id": str(DEAL_ID),
    }

    text, _ = renderer.telegram(
        NotificationType.DEAL_COMPLETION_PROMPT, params, DEAL_LINK, Locale.RU
    )

    assert text == (
        "<b>Работа выполнена?</b>\n"
        "&lt;b&gt;Ana&lt;/b&gt; &amp; Co: работа «Люстра» выполнена. Всё в порядке?"
    )


@pytest.mark.parametrize("locale", SCRIPTS)
def test_deal_texts_on_three_scripts(renderer: GettextNotificationRenderer, locale: Locale) -> None:
    cases: list[tuple[NotificationType, dict[str, str]]] = [
        (NotificationType.RESPONSE_ACCEPTED, {"title": "Люстра"}),
        (NotificationType.RESPONSE_NOT_SELECTED, {"title": "Люстра"}),
        (
            NotificationType.DEAL_PROPOSED,
            {
                "title": "Люстра",
                "by": "performer",
                "deal_id": str(DEAL_ID),
                "price_type": "fixed",
                "price": "350000",
            },
        ),
        (
            NotificationType.DEAL_CANCELLED,
            {"title": "Люстра", "by": "client", "reason": "other", "reopened": "true"},
        ),
        (NotificationType.DEAL_REMINDER, {"title": "Люстра", "at": "2026-10-03T17:00:00+00:00"}),
        (NotificationType.DEAL_COMPLETION_PROMPT, {"title": "Люстра", "deal_id": str(DEAL_ID)}),
        (
            NotificationType.DEAL_COMPLETION_PROMPT,
            {"title": "Люстра", "deal_id": str(DEAL_ID), "by": "client", "name": ""},
        ),
    ]
    for type_, params in cases:
        text, buttons = renderer.telegram(type_, params, DEAL_LINK, locale)
        assert "notifications." not in text, type_
        assert all("notifications." not in b.text for b in flat(buttons)), type_


REVIEW_LINK = encode_start_param(StartLink(type=LinkType.REVIEW, id=DEAL_ID))


@pytest.mark.parametrize("stage", ["first", "reminder", "last_call"])
@pytest.mark.parametrize("locale", SCRIPTS)
def test_review_request_asks_on_each_stage_with_a_button(
    renderer: GettextNotificationRenderer, stage: str, locale: Locale
) -> None:
    params = {"title": "Повесить люстру", "performer": "Алексей М.", "stage": stage}

    params |= {"deal_id": str(DEAL_ID)}

    text, [stars, form] = renderer.telegram(
        NotificationType.REVIEW_REQUEST, params, REVIEW_LINK, locale
    )

    assert "notifications." not in text
    assert "Алексей М." in text
    assert isinstance(stars, tuple)
    assert [star.text for star in stars] == ["1 ★", "2 ★", "3 ★", "4 ★", "5 ★"]
    assert all(isinstance(star, CallbackButton) for star in stars)
    assert [parse_callback(star.data) for star in stars if isinstance(star, CallbackButton)] == [
        CallbackData(CallbackAction.REVIEW_RATE, DEAL_ID, str(n)) for n in range(1, 6)
    ]
    assert isinstance(form, AppButton)
    assert form.url == f"{MINI_APP}?startapp={REVIEW_LINK}"  # сразу форма S27, без S26


def test_review_request_texts_in_russian(renderer: GettextNotificationRenderer) -> None:
    params = {"title": "Повесить люстру", "performer": "Алексей М."}

    first = renderer.text(NotificationType.REVIEW_REQUEST, params | {"stage": "first"}, Locale.RU)
    last = renderer.text(
        NotificationType.REVIEW_REQUEST, params | {"stage": "last_call"}, Locale.RU
    )
    odd = renderer.text(NotificationType.REVIEW_REQUEST, params | {"stage": "x"}, Locale.RU)

    assert first.title == "Оцените работу"
    assert first.body.startswith("«Повесить люстру», исполнитель — Алексей М.")
    assert last.title == "Осталось 2 дня, чтобы оставить отзыв"
    assert odd == first  # неизвестный этап — как первая просьба


def test_review_published_with_text_and_rating_only(renderer: GettextNotificationRenderer) -> None:
    with_text = renderer.text(
        NotificationType.REVIEW_PUBLISHED,
        {"rating": "5", "title": "Повесить люстру", "preview": "Всё отлично"},
        Locale.RU,
    )
    bare = renderer.text(
        NotificationType.REVIEW_PUBLISHED, {"rating": "4", "title": "Повесить люстру"}, Locale.RU
    )

    assert with_text.title == "Новый отзыв: 5 из 5"
    assert with_text.body == "«Всё отлично» — о работе «Повесить люстру»."
    assert bare.body == "Клиент поставил оценку без текста — работа «Повесить люстру»."


DISPUTE_LINK = encode_start_param(StartLink(type=LinkType.DISPUTE, id=DEAL_ID))


@pytest.mark.parametrize(
    ("by", "kind", "body"),
    [
        ("client", "no_show", "Клиент сообщил о проблеме со сделкой «Люстра»: не пришёл."),
        (
            "performer",
            "prepayment_taken",
            "Исполнитель сообщил о проблеме со сделкой «Люстра»:"
            " взял предоплату или просит больше.",
        ),
        ("client", "unknown", "Клиент сообщил о проблеме со сделкой «Люстра»: другое."),
    ],
)
def test_dispute_opened_tells_who_what_and_until_when(
    renderer: GettextNotificationRenderer, by: str, kind: str, body: str
) -> None:
    params = {"title": "Люстра", "by": by, "kind": kind, "until": "2026-10-05T17:40:00+00:00"}

    text, [answer] = renderer.telegram(
        NotificationType.DISPUTE_OPENED, params, DISPUTE_LINK, Locale.RU
    )

    assert text.startswith("<b>Проблема со сделкой</b>")
    first, deadline = text.split("\n")[1:]
    assert first == body
    assert deadline.startswith("Ответьте до 5 октября 2026")
    assert "19:40" in deadline  # Белград
    assert isinstance(answer, AppButton)
    assert (answer.text, answer.url) == ("Ответить", f"{MINI_APP}?startapp={DISPUTE_LINK}")


@pytest.mark.parametrize(
    ("outcome", "reason", "body"),
    [
        (
            "completed",
            "work_done",
            "Поддержка рассмотрела спор по сделке «Люстра»: сделка выполнена."
            " Причина: работа выполнена.",
        ),
        (
            "cancelled",
            "no_show",
            "Поддержка рассмотрела спор по сделке «Люстра»: сделка отменена."
            " Причина: встреча не состоялась.",
        ),
        (
            "cancelled",
            "something_new",
            "Поддержка рассмотрела спор по сделке «Люстра»: сделка отменена."
            " Причина: решение по материалам спора.",
        ),
    ],
)
def test_dispute_resolved_states_outcome_and_reason(
    renderer: GettextNotificationRenderer, outcome: str, reason: str, body: str
) -> None:
    text = renderer.text(
        NotificationType.DISPUTE_RESOLVED,
        {"title": "Люстра", "outcome": outcome, "reason": reason},
        Locale.RU,
    )

    assert (text.title, text.body) == ("Решение по спору", body)


@pytest.mark.parametrize("locale", SCRIPTS)
def test_dispute_texts_on_three_scripts(
    renderer: GettextNotificationRenderer, locale: Locale
) -> None:
    cases: list[tuple[NotificationType, dict[str, str]]] = [
        (
            NotificationType.DISPUTE_OPENED,
            {"title": "Люстра", "by": "performer", "kind": kind, "until": "2026-10-05T17:40:00Z"},
        )
        for kind in ("no_show", "quality", "prepayment_taken", "damage", "safety", "other")
    ] + [
        (
            NotificationType.DISPUTE_RESOLVED,
            {"title": "Люстра", "outcome": outcome, "reason": reason},
        )
        for outcome in ("completed", "cancelled")
        for reason in (
            "work_done",
            "not_done",
            "no_show",
            "poor_quality",
            "prepayment_scam",
            "no_response",
            "mutual",
            "other",
        )
    ]
    for type_, params in cases:
        text, buttons = renderer.telegram(type_, params, DISPUTE_LINK, locale)
        assert "notifications." not in text, (type_, params)
        assert [b.text for b in flat(buttons) if "notifications." in b.text] == []


@pytest.mark.parametrize(
    ("locale", "text", "button"),
    [
        (
            Locale.RU,
            "<b>Заявка опубликована</b>\nМодератор проверил «Люстра» — исполнители уже видят"
            " заявку. Бот напишет, когда придут отклики.",
            "Открыть заявку",
        ),
        (
            Locale.SR_LATN,
            "<b>Zahtev je objavljen</b>\nModerator je proverio „Lustra“ — izvođači već vide"
            " zahtev. Bot će vam javiti kada stignu ponude.",
            "Otvori zahtev",
        ),
        (
            Locale.SR_CYRL,
            "<b>Захтев је објављен</b>\nМодератор је проверио „Люстра“ — извођачи већ виде"
            " захтев. Бот ће вам јавити када стигну понуде.",
            "Отвори захтев",
        ),
    ],
)
def test_job_published_after_review_leads_to_the_job(
    renderer: GettextNotificationRenderer, locale: Locale, text: str, button: str
) -> None:
    """№11, G-A: заявку опубликовал модератор — что произошло, кто дальше и как узнать; кнопка —
    к заявке (S23 владельцу)."""
    title = "Lustra" if locale is Locale.SR_LATN else "Люстра"
    rendered, buttons = renderer.telegram(
        NotificationType.JOB_PUBLISHED, {"title": title}, JOB_LINK, locale
    )

    assert rendered == text
    assert opens(buttons) == [(button, f"{MINI_APP}?startapp={JOB_LINK}")]


@pytest.mark.parametrize(
    ("locale", "title"),
    [
        (Locale.RU, "Клиент отклонил отклик"),
        (Locale.SR_LATN, "Klijent je odbio ponudu"),
        (Locale.SR_CYRL, "Клијент је одбио понуду"),
    ],
)
def test_declined_response_is_named_by_its_status(
    renderer: GettextNotificationRenderer, locale: Locale, title: str
) -> None:
    """Строка центра S42 (в бот не уходит): заголовок — слово статуса S17 «Клиент отклонил»."""
    text = renderer.text(NotificationType.RESPONSE_DECLINED, {"title": "Люстра"}, locale)

    assert text.title == title
    assert "Люстра" in text.body
    assert "notifications." not in text.body


@pytest.mark.parametrize(
    ("by", "body"),
    [
        ("client", "Клиент подтвердил работу «Люстра»."),
        ("auto", "Работа «Люстра» засчитана: после отметки прошло 3 дня."),
        ("someone", "Клиент подтвердил работу «Люстра»."),
    ],
)
def test_completed_deal_tells_the_performer_who_confirmed(
    renderer: GettextNotificationRenderer, by: str, body: str
) -> None:
    """Исполнителю в S42: сделка «Выполнена» (слово статуса), кто подтвердил."""
    text = renderer.text(NotificationType.DEAL_COMPLETED, {"title": "Люстра", "by": by}, Locale.RU)

    assert (text.title, text.body) == ("Сделка выполнена", body)


@pytest.mark.parametrize("locale", SCRIPTS)
def test_outcome_texts_on_three_scripts(
    renderer: GettextNotificationRenderer, locale: Locale
) -> None:
    for type_, params in (
        (NotificationType.DEAL_COMPLETED, {"title": "Люстра", "by": "auto"}),
        (NotificationType.RESPONSE_DECLINED, {"title": "Люстра"}),
        (NotificationType.JOB_PUBLISHED, {"title": "Люстра"}),
    ):
        assert "notifications." not in full_text(renderer, type_, params, locale), type_


@pytest.mark.parametrize("locale", ["sr_Latn", "sr_Cyrl"])
def test_serbian_bot_says_klijent(locale: str) -> None:
    """№15: клиент по-сербски — «klijent» везде, как на экранах; «naručilac» не встречается."""
    catalog = LOCALES_DIR / locale / "LC_MESSAGES" / "messages.po"

    texts = catalog.read_text(encoding="utf-8").lower()

    assert "naruč" not in texts
    assert "наруч" not in texts
