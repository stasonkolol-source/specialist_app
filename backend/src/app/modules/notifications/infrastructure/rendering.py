"""Тексты уведомлений по шаблонам gettext (ADR-0013, ARCHITECTURE §11.3).

Шаблоны — простой текст в каталогах `notifications.*`, параметры — машинные значения из
payload: коды превращаются в слова каталога, даты — в время Белграда на языке читателя.
Для бота заголовок и текст экранируются целиком и заголовок выделяется `<b>`: ни шаблон,
ни параметр не внесут в сообщение разметку. Кнопка — web_app с кодом deep link; у срока
заявки (`job.expiring`, `job.expired`) — callback-кнопки «Продлить» и «Закрыть», у приглашения
(`job.invited`, 5.6) — «Посмотреть заявку» и «Откликнуться: «…»» на каждый шаблон получателя:
нажатие обрабатывает бот модуля jobs (platform/telegram/callbacks.py). У «Работа выполнена?»
(`deal.completion_prompt`, 6.1b) — callback «Да, выполнено» (бот deals) и web_app «Нет,
проблема» к сделке; у «Договорились?» (`deal.proposed`, 6.3b) — callback «Подтвердить» и
«Отклонить» (бот deals) и web_app «Посмотреть условия».

Шаблоны есть у типов, которые создаёт подписчик (tasks.py): тип без шаблонов — ошибка
программиста, её ловит тест на каталоги.
"""

import html
from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from uuid import UUID

from app.modules.notifications.application.dto import RenderedText
from app.modules.notifications.domain.catalog import NotificationType
from app.platform.i18n.dates import long_datetime
from app.platform.i18n.translator import Translator
from app.platform.kernel.localized import Locale
from app.platform.telegram.buttons import mini_app_url
from app.platform.telegram.callbacks import (
    CallbackAction,
    CallbackData,
    encode_callback,
    ref_arg,
)
from app.platform.telegram.port import AppButton, Button, ButtonLine, CallbackButton

RENDERED = frozenset(
    {
        NotificationType.ACCOUNT_RESTRICTED,
        NotificationType.MODERATION_DECISION,
        NotificationType.SYSTEM_TEST,
        NotificationType.PROFILE_PUBLISHED,
        NotificationType.JOB_EXPIRING,
        NotificationType.JOB_EXPIRED,
        NotificationType.RESPONSE_RECEIVED,
        NotificationType.JOB_INVITED,
        NotificationType.RESPONSE_ACCEPTED,
        NotificationType.RESPONSE_NOT_SELECTED,
        NotificationType.MESSAGE_RECEIVED,
        NotificationType.DEAL_PROPOSED,
        NotificationType.DEAL_CANCELLED,
        NotificationType.DEAL_REMINDER,
        NotificationType.DEAL_COMPLETION_PROMPT,
        NotificationType.REVIEW_REQUEST,
        NotificationType.REVIEW_PUBLISHED,
    }
)
"""Типы с шаблонами: остальные получат их вместе со своими подписчиками."""

SIDES = frozenset({"client", "performer"})
"""Кто отметил «Работа выполнена» (`by` у `deal.completion_prompt`, B2): свой текст вопроса."""
REVIEW_STAGES = frozenset({"first", "reminder", "last_call"})
"""Когда просим отзыв (ReviewRequested.stage): свой заголовок и текст у каждой."""

JOB_TERM = frozenset({NotificationType.JOB_EXPIRING, NotificationType.JOB_EXPIRED})
"""Срок заявки: «Продлить» (если ещё можно) и «Закрыть» — callback-кнопки бота jobs."""
FOUND = "found"
"""Аргумент «Закрыть» у `job.expiring`: спросить, где нашёлся исполнитель (callbacks.py)."""
TITLE_CHARS = 60
"""Название заявки в тексте — не длиннее, дальше «…»."""
TEMPLATE_BUTTONS = 2
"""Кнопок «Откликнуться: «…»» — по шаблонам получателя (их не больше двух)."""

BUTTONS: Mapping[NotificationType, str] = MappingProxyType(
    {
        NotificationType.ACCOUNT_RESTRICTED: "notifications.account_restricted.button",
        NotificationType.MODERATION_DECISION: "notifications.moderation_decision.button",
        NotificationType.SYSTEM_TEST: "notifications.system_test.button",
        NotificationType.PROFILE_PUBLISHED: "notifications.profile_published.button",
        NotificationType.RESPONSE_RECEIVED: "notifications.response_received.button",
        NotificationType.RESPONSE_ACCEPTED: "notifications.deal.open",
        NotificationType.MESSAGE_RECEIVED: "notifications.message_received.button",
        NotificationType.DEAL_CANCELLED: "notifications.deal.open",
        NotificationType.DEAL_REMINDER: "notifications.deal.open",
        NotificationType.REVIEW_PUBLISHED: "notifications.review_published.button",
    }
)
"""Подпись кнопки бота; ведёт она по коду deep link уведомления."""

TITLED: Mapping[NotificationType, str] = MappingProxyType(
    {
        NotificationType.RESPONSE_ACCEPTED: "response_accepted",
        NotificationType.RESPONSE_NOT_SELECTED: "response_not_selected",
        NotificationType.DEAL_COMPLETION_PROMPT: "deal_completion_prompt",
    }
)
"""Шаблоны «заголовок + текст с названием»: `notifications.<ключ>.title` и `.body`."""

DEAL_CANCEL_REASONS = frozenset({"plans_changed", "no_agreement", "no_contact", "other"})
"""Причины, которые выбирает сторона (`deal_cancel_reason.*`); `expired` и `account_deleted` —
свои тексты отмены системой."""

PRICE_TYPES = frozenset({"fixed", "from", "hourly"})
"""Цена с суммой (`notifications.price.*`); договорная — без суммы."""

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
        if type_ in JOB_TERM:
            return self._job_term(type_, params, locale)
        if type_ is NotificationType.RESPONSE_RECEIVED:
            return self._responses(params, locale)
        if type_ is NotificationType.JOB_INVITED:
            return self._invited(params, locale)
        if type_ is NotificationType.MESSAGE_RECEIVED:
            return self._message_received(params, locale)
        if type_ is NotificationType.DEAL_PROPOSED:
            return self._deal_proposed(params, locale)
        if type_ is NotificationType.DEAL_CANCELLED:
            return self._deal_cancelled(params, locale)
        if type_ is NotificationType.DEAL_REMINDER:
            return RenderedText(
                title=self._t("notifications.deal_reminder.title", locale),
                body=self._t(
                    "notifications.deal_reminder.body",
                    locale,
                    title=_short(params.get("title")),
                    when=self._datetime(params.get("at", ""), locale),
                ),
            )
        if type_ is NotificationType.DEAL_COMPLETION_PROMPT and params.get("by") in SIDES:
            return RenderedText(
                title=self._t("notifications.deal_completion_prompt.title", locale),
                body=self._t(
                    f"notifications.deal_completion_prompt.body_marked_{params['by']}",
                    locale,
                    title=_short(params.get("title")),
                ),
            )
        if type_ is NotificationType.REVIEW_REQUEST:
            stage = params.get("stage", "first")
            stage = stage if stage in REVIEW_STAGES else "first"
            return RenderedText(
                title=self._t(f"notifications.review_request.title_{stage}", locale),
                body=self._t(
                    f"notifications.review_request.body_{stage}",
                    locale,
                    title=_short(params.get("title")),
                    performer=params.get("performer", ""),
                ),
            )
        if type_ is NotificationType.REVIEW_PUBLISHED:
            title = _short(params.get("title"))
            preview = params.get("preview")
            return RenderedText(
                title=self._t(
                    "notifications.review_published.title",
                    locale,
                    rating=params.get("rating", ""),
                ),
                body=(
                    self._t(
                        "notifications.review_published.body", locale, text=preview, title=title
                    )
                    if preview
                    else self._t("notifications.review_published.body_rating", locale, title=title)
                ),
            )
        if type_ in TITLED:
            key, title = TITLED[type_], _short(params.get("title"))
            return RenderedText(
                title=self._t(f"notifications.{key}.title", locale),
                body=self._t(f"notifications.{key}.body", locale, title=title),
            )
        if type_ is NotificationType.PROFILE_PUBLISHED:
            return RenderedText(
                title=self._t("notifications.profile_published.title", locale),
                body=self._t("notifications.profile_published.body", locale),
            )
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
    ) -> tuple[str, tuple[ButtonLine, ...]]:
        text = self.text(type_, params, locale)
        message = f"<b>{_escape(text.title)}</b>\n{_escape(text.body)}"
        if type_ in JOB_TERM:
            return message, self._job_buttons(type_, params, locale)
        if type_ is NotificationType.JOB_INVITED:
            return message, self._invite_buttons(params, link, locale)
        if type_ is NotificationType.DEAL_COMPLETION_PROMPT:
            return message, self._completion_buttons(params, link, locale)
        if type_ is NotificationType.DEAL_PROPOSED:
            return message, self._proposal_buttons(params, link, locale)
        if type_ is NotificationType.REVIEW_REQUEST:
            return message, self._review_buttons(params, link, locale)
        label = BUTTONS.get(type_)
        if label is None or link is None or self._mini_app is None:
            return message, ()
        button = AppButton(text=self._t(label, locale), url=mini_app_url(self._mini_app, link))
        return message, (button,)

    def _job_term(
        self, type_: NotificationType, params: Mapping[str, str], locale: Locale
    ) -> RenderedText:
        key = "job_expiring" if type_ is NotificationType.JOB_EXPIRING else "job_expired"
        body = "body" if params.get("can_extend") == "true" else "body_final"
        return RenderedText(
            title=self._t(f"notifications.{key}.title", locale),
            body=self._t(f"notifications.{key}.{body}", locale, title=_short(params.get("title"))),
        )

    def _job_buttons(
        self, type_: NotificationType, params: Mapping[str, str], locale: Locale
    ) -> tuple[ButtonLine, ...]:
        try:
            job_id = UUID(params.get("job_id", ""))
        except ValueError:
            return ()
        buttons: list[Button] = []
        if params.get("can_extend") == "true":
            buttons.append(
                CallbackButton(
                    text=self._t("notifications.job.extend", locale),
                    data=encode_callback(CallbackData(CallbackAction.JOB_EXTEND, job_id)),
                )
            )
        found = type_ is NotificationType.JOB_EXPIRING
        buttons.append(
            CallbackButton(
                text=self._t(
                    "notifications.job.close_found" if found else "notifications.job.close", locale
                ),
                data=encode_callback(
                    CallbackData(CallbackAction.JOB_CLOSE, job_id, FOUND if found else None)
                ),
            )
        )
        return tuple(buttons)

    def _deal_cancelled(self, params: Mapping[str, str], locale: Locale) -> RenderedText:
        """Кто отменил и почему: «Клиент отменил сделку «…»: планы изменились»; отмена системой —
        своим текстом; клиенту из отклика — «Заявка снова открыта»."""
        title = _short(params.get("title"))
        reason = params.get("reason", "")
        by = params.get("by", "")
        if reason in DEAL_CANCEL_REASONS and by in {"client", "performer"}:
            body = self._t(
                f"notifications.deal_cancelled.body_{by}",
                locale,
                title=title,
                reason=self._t(f"notifications.deal_cancel_reason.{reason}", locale),
            )
        else:
            system = reason if reason in {"expired", "account_deleted"} else "other"
            body = self._t(f"notifications.deal_cancelled.body_{system}", locale, title=title)
        if params.get("reopened") == "true":
            body = f"{body} {self._t('notifications.deal_cancelled.reopened', locale)}"
        return RenderedText(title=self._t("notifications.deal_cancelled.title", locale), body=body)

    def _message_received(self, params: Mapping[str, str], locale: Locale) -> RenderedText:
        """«Алексей пишет» и начало сообщения; несколько — ещё и сколько их. Без текста (контакт,
        скрытое модерацией) — только сколько."""
        name = (params.get("name") or "").strip()
        name = _short(name) if name else self._t("notifications.message_received.someone", locale)
        count, preview = params.get("count", "1"), params.get("preview")
        lines = []
        if preview:
            lines.append(self._t("notifications.message_received.preview", locale, text=preview))
        if count != "1" or not preview:
            lines.append(self._t("notifications.message_received.count", locale, count=count))
        return RenderedText(
            title=self._t("notifications.message_received.title", locale, name=name),
            body="\n".join(lines),
        )

    def _deal_proposed(self, params: Mapping[str, str], locale: Locale) -> RenderedText:
        """Кто предлагает и что: название, когда и цена — решить можно прямо в чате бота."""
        by = "client" if params.get("by") == "client" else "performer"
        lines = [
            self._t(
                f"notifications.deal_proposed.body_{by}", locale, title=_short(params.get("title"))
            )
        ]
        if at := params.get("at"):
            lines.append(
                self._t("notifications.deal_proposed.when", locale, when=self._datetime(at, locale))
            )
        if price := self._price(params.get("price_type"), params.get("price"), locale):
            lines.append(self._t("notifications.deal_proposed.price", locale, price=price))
        lines.append(self._t("notifications.deal_proposed.deadline", locale))
        return RenderedText(
            title=self._t("notifications.deal_proposed.title", locale), body="\n".join(lines)
        )

    def _price(self, price_type: str | None, amount: str | None, locale: Locale) -> str | None:
        """Цена сделки словами языка: «3 500 RSD», «от 3 500 RSD», «договорная»."""
        if price_type == "negotiable":
            return self._t("notifications.price.negotiable", locale)
        if price_type not in PRICE_TYPES or amount is None or not amount.isdigit():
            return None
        return self._t(
            f"notifications.price.{price_type}", locale, amount=_money(int(amount), locale)
        )

    def _proposal_buttons(
        self, params: Mapping[str, str], link: str | None, locale: Locale
    ) -> tuple[ButtonLine, ...]:
        """«Подтвердить» и «Отклонить» — ответ прямо из чата (бот deals); «Посмотреть условия» —
        к предложению в Mini App (S53)."""
        buttons: list[Button] = []
        try:
            deal_id = UUID(params.get("deal_id", ""))
        except ValueError:
            pass
        else:
            for action, key in (
                (CallbackAction.DEAL_CONFIRM, "notifications.deal_proposed.confirm"),
                (CallbackAction.DEAL_DECLINE, "notifications.deal_proposed.decline"),
            ):
                buttons.append(
                    CallbackButton(
                        text=self._t(key, locale),
                        data=encode_callback(CallbackData(action, deal_id)),
                    )
                )
        if link is not None and self._mini_app is not None:
            buttons.append(
                AppButton(
                    text=self._t("notifications.deal_proposed.button", locale),
                    url=mini_app_url(self._mini_app, link),
                )
            )
        return tuple(buttons)

    def _review_buttons(
        self, params: Mapping[str, str], link: str | None, locale: Locale
    ) -> tuple[ButtonLine, ...]:
        """B2: «1 ★ … 5 ★» одним рядом — оценка без текста прямо из чата (бот reviews); ниже —
        «Открыть форму отзыва» (сделка S26 → S27)."""
        lines: list[ButtonLine] = []
        try:
            deal_id = UUID(params.get("deal_id", ""))
        except ValueError:
            pass
        else:
            lines.append(
                tuple(
                    CallbackButton(
                        text=f"{stars} ★",
                        data=encode_callback(
                            CallbackData(CallbackAction.REVIEW_RATE, deal_id, str(stars))
                        ),
                    )
                    for stars in range(1, 6)
                )
            )
        if link is not None and self._mini_app is not None:
            lines.append(
                AppButton(
                    text=self._t("notifications.review_request.button", locale),
                    url=mini_app_url(self._mini_app, link),
                )
            )
        return tuple(lines)

    def _completion_buttons(
        self, params: Mapping[str, str], link: str | None, locale: Locale
    ) -> tuple[ButtonLine, ...]:
        """Один ряд (B2): «Да, всё хорошо» — отметка в сделке прямо из чата (бот deals); «Есть
        проблема» — к сделке в Mini App (спор S52 — 6.2)."""
        buttons: list[Button] = []
        try:
            deal_id = UUID(params.get("deal_id", ""))
        except ValueError:
            pass
        else:
            buttons.append(
                CallbackButton(
                    text=self._t("notifications.deal_completion_prompt.yes", locale),
                    data=encode_callback(CallbackData(CallbackAction.DEAL_COMPLETE, deal_id)),
                )
            )
        if link is not None and self._mini_app is not None:
            buttons.append(
                AppButton(
                    text=self._t("notifications.deal_completion_prompt.problem", locale),
                    url=mini_app_url(self._mini_app, link),
                )
            )
        return (tuple(buttons),) if buttons else ()

    def _invited(self, params: Mapping[str, str], locale: Locale) -> RenderedText:
        """«Вас приглашают откликнуться» или «Прямой запрос»: кто и на какую заявку."""
        key = "_direct" if params.get("direct") == "true" else ""
        client = params.get("client") or self._t("notifications.job_invited.client", locale)
        return RenderedText(
            title=self._t(f"notifications.job_invited.title{key}", locale),
            body=self._t(
                f"notifications.job_invited.body{key}",
                locale,
                client=client,
                title=_short(params.get("title")),
            ),
        )

    def _invite_buttons(
        self, params: Mapping[str, str], link: str | None, locale: Locale
    ) -> tuple[ButtonLine, ...]:
        """«Посмотреть заявку» и «Откликнуться: «Могу сегодня»» — на каждый шаблон."""
        buttons: list[Button] = []
        if link is not None and self._mini_app is not None:
            buttons.append(
                AppButton(
                    text=self._t("notifications.job_invited.button", locale),
                    url=mini_app_url(self._mini_app, link),
                )
            )
        try:
            job_id = UUID(params.get("job_id", ""))
        except ValueError:
            return tuple(buttons)
        for index in range(TEMPLATE_BUTTONS):
            try:
                template_id = UUID(params.get(f"template_{index}", ""))
            except ValueError:
                continue
            title = params.get(f"template_{index}_title", "")
            buttons.append(
                CallbackButton(
                    text=self._t("notifications.job_invited.template", locale, title=title),
                    data=encode_callback(
                        CallbackData(CallbackAction.JOB_RESPOND, job_id, ref_arg(template_id))
                    ),
                )
            )
        return tuple(buttons)

    def _responses(self, params: Mapping[str, str], locale: Locale) -> RenderedText:
        """«Новый отклик» или «Новых откликов: 3» — на заявку «Повесить люстру»."""
        count = int(params.get("count") or 1)
        title = _short(params.get("title"))
        body = (
            self._t("notifications.response_received.body_one", locale, title=title)
            if count == 1
            else self._t(
                "notifications.response_received.body_many", locale, title=title, count=count
            )
        )
        return RenderedText(
            title=self._t("notifications.response_received.title", locale), body=body
        )

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
        return long_datetime(datetime.fromisoformat(value), locale)


def _escape(text: str) -> str:
    return html.escape(text, quote=False)


def _money(amount: int, locale: Locale) -> str:
    """Сумма в пара — динарами по правилам языка: «3 500» (ru), «3.500» (sr), копейки — после
    запятой."""
    whole, cents = divmod(amount, 100)
    separator = "\u00a0" if locale is Locale.RU else "."
    text = f"{whole:,}".replace(",", separator)
    return f"{text},{cents:02d}" if cents else text


def _short(title: str | None) -> str:
    title = (title or "").strip()
    return title if len(title) <= TITLE_CHARS else title[: TITLE_CHARS - 1].rstrip() + "…"
