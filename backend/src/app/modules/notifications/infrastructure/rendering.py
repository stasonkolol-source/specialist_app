"""Тексты уведомлений по шаблонам gettext (ADR-0013, ARCHITECTURE §11.3).

Шаблоны — простой текст в каталогах `notifications.*`, параметры — машинные значения из
payload: коды превращаются в слова каталога, даты — в время Белграда на языке читателя.
Для бота заголовок и текст экранируются целиком и заголовок выделяется `<b>`: ни шаблон,
ни параметр не внесут в сообщение разметку. Кнопка — web_app с кодом deep link.

Шаблоны есть у типов, которые создаёт подписчик (tasks.py): тип без шаблонов — ошибка
программиста, её ловит тест на каталоги.
"""

import html
from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType

import babel
from babel.dates import format_datetime

from app.modules.notifications.application.dto import RenderedText
from app.modules.notifications.domain.catalog import NotificationType
from app.modules.notifications.domain.settings import TIMEZONE
from app.platform.i18n.catalogs import CATALOG_NAMES
from app.platform.i18n.translator import Translator
from app.platform.kernel.localized import Locale
from app.platform.telegram.buttons import mini_app_url
from app.platform.telegram.port import AppButton

RENDERED = frozenset(
    {
        NotificationType.ACCOUNT_RESTRICTED,
        NotificationType.MODERATION_DECISION,
        NotificationType.SYSTEM_TEST,
    }
)
"""Типы с шаблонами: остальные получат их вместе со своими подписчиками."""

BUTTONS: Mapping[NotificationType, str] = MappingProxyType(
    {
        NotificationType.ACCOUNT_RESTRICTED: "notifications.account_restricted.button",
        NotificationType.MODERATION_DECISION: "notifications.moderation_decision.button",
        NotificationType.SYSTEM_TEST: "notifications.system_test.button",
    }
)
"""Подпись кнопки бота; ведёт она по коду deep link уведомления."""

PROHIBITED = frozenset({"drug_courier", "sexual_services", "weapons"})
"""Метки ADR-0016, которые человеку называются одинаково: запрещённые товары и услуги."""


class GettextNotificationRenderer:
    def __init__(self, translator: Translator, mini_app: str | None) -> None:
        self._translator = translator
        self._mini_app = mini_app
        """Адрес Mini App (TELEGRAM_MINI_APP_URL); нет — сообщения без кнопок."""

    def renders(self, type_: NotificationType) -> bool:
        return type_ in RENDERED

    def text(
        self, type_: NotificationType, params: Mapping[str, str], locale: Locale
    ) -> RenderedText:
        if type_ is NotificationType.ACCOUNT_RESTRICTED:
            return self._account_restricted(params, locale)
        if type_ is NotificationType.MODERATION_DECISION:
            return self._moderation_decision(params, locale)
        if type_ is NotificationType.SYSTEM_TEST:
            return RenderedText(
                title=self._t("notifications.system_test.title", locale),
                body=self._t("notifications.system_test.body", locale),
            )
        raise ValueError(f"no templates for notification type {type_}")

    def telegram(
        self,
        type_: NotificationType,
        params: Mapping[str, str],
        link: str | None,
        locale: Locale,
    ) -> tuple[str, tuple[AppButton, ...]]:
        text = self.text(type_, params, locale)
        message = f"<b>{_escape(text.title)}</b>\n{_escape(text.body)}"
        label = BUTTONS.get(type_)
        if label is None or link is None or self._mini_app is None:
            return message, ()
        button = AppButton(text=self._t(label, locale), url=mini_app_url(self._mini_app, link))
        return message, (button,)

    def _account_restricted(self, params: Mapping[str, str], locale: Locale) -> RenderedText:
        kind = params.get("kind", "")
        title = "banned" if kind == "banned" else "restricted"
        parts = [self._t(f"notifications.account_restricted.body.{kind}", locale)]
        if until := params.get("until"):
            when = self._datetime(until, locale)
            parts.append(self._t("notifications.account_restricted.until", locale, until=when))
        parts.append(self._t("notifications.account_restricted.rules", locale))
        return RenderedText(
            title=self._t(f"notifications.account_restricted.title.{title}", locale),
            body=" ".join(parts),
        )

    def _moderation_decision(self, params: Mapping[str, str], locale: Locale) -> RenderedText:
        entity = params.get("entity_type", "")
        code = params.get("decision_code") or "other"
        if code in PROHIBITED:
            code = "prohibited"
        reason = self._first(
            locale,
            f"notifications.moderation_reason.{code}",
            "notifications.moderation_reason.other",
        )
        parts = [self._t("notifications.moderation_decision.body", locale, reason=reason)]
        if params.get("sanction") == "warning":  # о санкции с ограничением — account.restricted
            parts.append(self._t("notifications.moderation_decision.warning", locale))
        if automated := params.get("automated"):  # в параметрах с 2.5a
            who = "automated" if automated == "true" else "by_moderator"
            parts.append(self._t(f"notifications.moderation_decision.{who}", locale))
        return RenderedText(
            title=self._first(
                locale,
                f"notifications.moderation_decision.title.{entity}",
                "notifications.moderation_decision.title.other",
            ),
            body=" ".join(parts),
        )

    def _t(self, key: str, locale: Locale, **params: object) -> str:
        """Текст ключа; ключа нет ни в одном каталоге — сам ключ (пропуск виден в тесте)."""
        return self._translator.text(key, locale, **params) or key

    def _first(self, locale: Locale, key: str, fallback: str) -> str:
        """Текст ключа или запасного: коды причин и видов контента открыты для модерации."""
        return self._translator.text(key, locale) or self._t(fallback, locale)

    def _datetime(self, value: str, locale: Locale) -> str:
        """Дата и время по Белграду в формате языка: «12 октября 2026 г., 08:30»."""
        moment = datetime.fromisoformat(value)
        cldr = babel.Locale.parse(CATALOG_NAMES[locale])
        long_date = cldr.date_formats["long"].pattern
        pattern = cldr.datetime_formats["long"].replace("{1}", long_date).replace("{0}", "HH:mm")
        return format_datetime(moment, pattern, tzinfo=TIMEZONE, locale=cldr)


def _escape(text: str) -> str:
    return html.escape(text, quote=False)
