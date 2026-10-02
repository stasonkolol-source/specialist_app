"""Тексты уведомлений на трёх письменностях (DEVELOPMENT_PLAN 2.3a, ADR-0013).

Каталоги — настоящие (backend/locales): ключ, которого нет, вылез бы в текст как есть.
"""

from collections.abc import Mapping
from uuid import UUID

import pytest

from app.modules.notifications.domain.catalog import NotificationType
from app.modules.notifications.infrastructure.rendering import RENDERED, GettextNotificationRenderer
from app.platform.contracts.events.identity import RestrictionKind
from app.platform.i18n.translator import Translator
from app.platform.kernel.localized import Locale
from app.platform.telegram.callbacks import CallbackAction, CallbackData, parse_callback
from app.platform.telegram.deeplinks import parse_start_param
from app.platform.telegram.port import AppButton, CallbackButton

pytestmark = pytest.mark.unit

SCRIPTS = (Locale.RU, Locale.SR_CYRL, Locale.SR_LATN)
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
    assert "12. октобар 2026. 08:30" in texts[Locale.SR_CYRL]
    assert texts[Locale.SR_LATN].startswith("Nalog je ograničen\n")
    assert "12. oktobar 2026. 08:30" in texts[Locale.SR_LATN]


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

    assert text.startswith("<b>Заявка не опубликована</b>\n")
    assert "<b>x</b>" not in text  # неизвестный код — общие слова; разметку он не вносит
    [button] = buttons
    assert isinstance(button, AppButton)
    assert button.text == "Исправить"
    assert button.url == f"{MINI_APP}?startapp=l_terms"
    assert parse_start_param("l_terms") is not None


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


def test_types_without_templates_are_refused(renderer: GettextNotificationRenderer) -> None:
    assert set(RENDERED) == {
        RESTRICTED,
        DECISION,
        NotificationType.SYSTEM_TEST,
        NotificationType.PROFILE_PUBLISHED,
        NotificationType.JOB_EXPIRING,
        NotificationType.JOB_EXPIRED,
    }
    with pytest.raises(ValueError, match="no templates"):
        renderer.text(NotificationType.JOB_MATCHED, {}, Locale.RU)


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
    assert len(buttons) == 1


JOB_ID = UUID("01a0fc88-f156-726a-9a76-99e3d10e5542")


def job_params(*, can_extend: bool, title: str = "Повесить люстру") -> dict[str, str]:
    return {"job_id": str(JOB_ID), "title": title, "can_extend": "true" if can_extend else "false"}


def callbacks(buttons: tuple[object, ...]) -> list[tuple[str, CallbackData | None]]:
    assert all(isinstance(b, CallbackButton) for b in buttons)
    return [(b.text, parse_callback(b.data)) for b in buttons if isinstance(b, CallbackButton)]


def test_expiring_job_offers_extend_and_close_as_found(
    renderer: GettextNotificationRenderer,
) -> None:
    text, buttons = renderer.telegram(
        NotificationType.JOB_EXPIRING, job_params(can_extend=True), "j_abc", Locale.RU
    )

    assert text == (
        "<b>Заявка скоро закроется</b>\n«Повесить люстру» закроется через 2 часа."
        " Если исполнитель ещё нужен — продлите заявку."
    )
    assert callbacks(buttons) == [
        ("Продлить", CallbackData(CallbackAction.JOB_EXTEND, JOB_ID)),
        ("Закрыть: исполнитель найден", CallbackData(CallbackAction.JOB_CLOSE, JOB_ID, "found")),
    ]


def test_expired_job_after_three_extensions_can_only_be_closed(
    renderer: GettextNotificationRenderer,
) -> None:
    text, buttons = renderer.telegram(
        NotificationType.JOB_EXPIRED, job_params(can_extend=False), "j_abc", Locale.RU
    )

    assert "Продлевать её больше нельзя" in text
    assert callbacks(buttons) == [("Закрыть", CallbackData(CallbackAction.JOB_CLOSE, JOB_ID))]


@pytest.mark.parametrize("locale", SCRIPTS)
@pytest.mark.parametrize("type_", [NotificationType.JOB_EXPIRING, NotificationType.JOB_EXPIRED])
def test_job_term_texts_on_three_scripts(
    renderer: GettextNotificationRenderer, type_: NotificationType, locale: Locale
) -> None:
    for can_extend in (True, False):
        text, buttons = renderer.telegram(type_, job_params(can_extend=can_extend), None, locale)
        assert "notifications." not in text
        assert all("notifications." not in b.text for b in buttons)


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
