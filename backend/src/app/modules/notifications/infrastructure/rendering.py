"""Тексты уведомлений по шаблонам gettext (ADR-0013, ARCHITECTURE §11.3).

Шаблоны — простой текст в каталогах `notifications.*`, параметры — машинные значения из
payload: коды превращаются в слова каталога, даты — в время Белграда на языке читателя.
Для бота заголовок и текст экранируются целиком и заголовок выделяется `<b>`: ни шаблон,
ни параметр не внесут в сообщение разметку. Кнопка — web_app с кодом deep link; у срока
заявки (`job.expiring`, `job.expired`) — callback-кнопки «Продлить» и «Закрыть», у приглашения
(`job.invited`, 5.6) — «Посмотреть заявку» и «Откликнуться: «…»» на каждый шаблон получателя:
нажатие обрабатывает бот модуля jobs (platform/telegram/callbacks.py). У «Работа выполнена?»
(`deal.completion_prompt`, 6.1b; после отметки второй стороны — «Алексей: работа «…» выполнена»,
B2) — callback «Да, выполнено» (бот deals) и web_app «Есть проблема» сразу на спор S52 (`p_`,
6.1c); у «Договорились?» (`deal.proposed`, 6.3b) — callback «Подтвердить» и «Отклонить» (бот
deals) и web_app «Посмотреть условия». Спор (6.1c): `dispute.opened` — «Ответить» на S52,
`dispute.resolved` — «Посмотреть решение». Подписки на заявки (5.7): `job.matched` — карточка B1
(название жирным, бюджет, район и расстояние, когда, места и подписка) с «Открыть заявку»,
«Откликнуться шаблоном «…»» на каждый шаблон получателя, «Не подходит» и «Пауза подписки» (их
обрабатывает бот jobs); закрытой заявке кнопки гасятся (`retired_buttons`). Бюджет и время B1 —
те же строки, что в карточке «Поделиться» (platform/i18n/jobs.py). `job.digest` — подборка по
подпискам с «Открыть ленту», `profile.stale_reminder` — «Включить «Доступен сегодня»» (S38) и
«Обновить профиль» (S33).

Шаблоны есть у типов, которые создаёт подписчик (tasks.py): тип без шаблонов — ошибка
программиста, её ловит тест на каталоги.
"""

import html
from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from uuid import UUID

from app.modules.notifications.application.dto import BroadcastContent, RenderedText
from app.modules.notifications.domain.broadcast import BroadcastAction
from app.modules.notifications.domain.catalog import NotificationType
from app.platform.i18n.dates import long_datetime
from app.platform.i18n.jobs import budget, price, when
from app.platform.i18n.translator import Translator
from app.platform.kernel.clock import Clock, SystemClock
from app.platform.kernel.localized import Locale, LocalizedText
from app.platform.telegram.buttons import mini_app_url
from app.platform.telegram.callbacks import (
    CallbackAction,
    CallbackData,
    encode_callback,
    ref_arg,
)
from app.platform.telegram.deeplinks import (
    LinkSection,
    LinkType,
    StartLink,
    encode_start_param,
)
from app.platform.telegram.port import (
    AppButton,
    Button,
    ButtonLine,
    CallbackButton,
    InactiveButton,
)

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
        NotificationType.DISPUTE_OPENED,
        NotificationType.DISPUTE_RESOLVED,
        NotificationType.JOB_MATCHED,
        NotificationType.JOB_DIGEST,
        NotificationType.PROFILE_STALE_REMINDER,
        NotificationType.BROADCAST,
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
        NotificationType.DISPUTE_OPENED: "notifications.dispute_opened.button",
        NotificationType.DISPUTE_RESOLVED: "notifications.dispute_resolved.button",
        NotificationType.JOB_DIGEST: "notifications.job_digest.button",
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

JOB_CLOSED = "job_closed"
"""`reason` у `response.not_selected`: заявку закрыли — свой заголовок и текст, без «выбрал
другого» (`notifications.response_job_closed.*`)."""

DEAL_CANCEL_REASONS = frozenset({"plans_changed", "no_agreement", "no_contact", "other"})
"""Причины, которые выбирает сторона (`deal_cancel_reason.*`); `expired` и `account_deleted` —
свои тексты отмены системой."""

DISPUTE_KINDS = frozenset({"no_show", "quality", "prepayment_taken", "damage", "safety", "other"})
"""Что случилось (DisputeKind, S52): `notifications.dispute_kind.*`."""
DISPUTE_OUTCOMES = frozenset({"completed", "cancelled"})

PROHIBITED = frozenset({"drug_courier", "sexual_services", "weapons"})

DIGEST_LINES = 10
"""Подписок в подборке строками: больше у человека и не бывает (MAX_ALERTS)."""
AVAILABILITY_LINK = encode_start_param(
    StartLink(type=LinkType.MINE, section=LinkSection.AVAILABILITY)
)
CABINET_LINK = encode_start_param(StartLink(type=LinkType.MINE, section=LinkSection.PROFILE))
KM = 1000
"""Метки ADR-0016, которые человеку называются одинаково: запрещённые товары и услуги."""


class GettextNotificationRenderer:
    def __init__(
        self, translator: Translator, mini_app: str | None, clock: Clock | None = None
    ) -> None:
        self._translator = translator
        self._mini_app = mini_app
        """Адрес Mini App (TELEGRAM_MINI_APP_URL); нет — сообщения без кнопок."""
        self._clock = clock or SystemClock()
        """«Сегодня» и «завтра» в карточке B1 — от момента показа: доставку могли отложить на
        конец тихих часов."""

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
            return self._marked_done(params["by"], params, locale)
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
        if type_ is NotificationType.DISPUTE_OPENED:
            return self._dispute_opened(params, locale)
        if type_ is NotificationType.DISPUTE_RESOLVED:
            return self._dispute_resolved(params, locale)
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
            if (
                type_ is NotificationType.RESPONSE_NOT_SELECTED
                and params.get("reason") == JOB_CLOSED
            ):
                key = "response_job_closed"  # клиент закрыл или удалил заявку (MU-11)
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
        if type_ is NotificationType.JOB_MATCHED:
            headline, *lines = self._match_lines(params, locale)
            return RenderedText(
                title=self._match_title(params, locale), body="\n".join([headline, *lines])
            )
        if type_ is NotificationType.JOB_DIGEST:
            return self._digest(params, locale)
        if type_ is NotificationType.PROFILE_STALE_REMINDER:
            return RenderedText(
                title=self._t("notifications.profile_stale_reminder.title", locale),
                body=self._t("notifications.profile_stale_reminder.body", locale),
            )
        if type_ is NotificationType.BROADCAST:  # текст — у рассылки (broadcast()), в центре её нет
            return RenderedText(title=self._t("notifications.broadcast.title", locale), body="")
        raise ValueError(f"no templates for notification type {type_}")

    def telegram(
        self,
        type_: NotificationType,
        params: Mapping[str, str],
        link: str | None,
        locale: Locale,
    ) -> tuple[str, tuple[ButtonLine, ...]]:
        if type_ is NotificationType.JOB_MATCHED:
            return self._match_card(params, locale), self._match_buttons(params, link, locale)
        text = self.text(type_, params, locale)
        message = f"<b>{_escape(text.title)}</b>\n{_escape(text.body)}"
        if type_ is NotificationType.PROFILE_STALE_REMINDER:
            return message, self._stale_buttons(locale)
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
        if params.get("entity_type") == "appeal":  # итог апелляции: исправлять нечего
            label = "notifications.appeal_decided.button"
        if label is None or link is None or self._mini_app is None:
            return message, ()
        button = AppButton(text=self._t(label, locale), url=mini_app_url(self._mini_app, link))
        return message, (button,)

    def broadcast(
        self, content: BroadcastContent, locale: Locale
    ) -> tuple[str, tuple[ButtonLine, ...]]:
        """Текст рассылки на языке читателя (цепочка §7.4) — экранирован целиком: разметки из
        админки в сообщении нет, и неверный HTML не сорвёт рассылку ответом 400."""
        message = _escape(LocalizedText.from_mapping(content.text).get(locale))
        if content.action == BroadcastAction.PRO_WAITLIST.value:
            data = encode_callback(CallbackData(CallbackAction.PRO_WAITLIST, content.id))
            label = self._t("notifications.broadcast.pro_waitlist", locale)
            return message, (CallbackButton(text=label, data=data),)
        if content.link is None or self._mini_app is None:
            return message, ()
        url = mini_app_url(self._mini_app, content.link)
        return message, (AppButton(text=self._t("notifications.broadcast.open", locale), url=url),)

    def retired_buttons(
        self,
        type_: NotificationType,  # noqa: ARG002 — гаснут пока только карточки B1
        params: Mapping[str, str],  # noqa: ARG002
        link: str | None,
        locale: Locale,
    ) -> tuple[ButtonLine, ...]:
        """Кнопки карточки B1, когда заявка больше не принимает отклики: «Открыть заявку»
        остаётся, вместо остальных — неактивная «Приём откликов закрыт». Других карточек с
        гаснущими кнопками пока нет: тип и параметры — на вырост."""
        closed = InactiveButton(text=self._t("notifications.job_matched.closed", locale))
        if link is None or self._mini_app is None:
            return (closed,)
        open_job = AppButton(
            text=self._t("notifications.job_matched.open", locale),
            url=mini_app_url(self._mini_app, link),
        )
        return open_job, closed

    def _match_title(self, params: Mapping[str, str], locale: Locale) -> str:
        """«Новая заявка рядом» — у подписки с радиусом; у районов и всего города — «по
        подписке»."""
        near = params.get("distance_m", "").isdigit()
        return self._t(f"notifications.job_matched.{'title' if near else 'title_alert'}", locale)

    def _match_lines(self, params: Mapping[str, str], locale: Locale) -> list[str]:
        """Строки карточки B1 простым текстом: «Повесить люстру · 5 000 RSD», «Лиман, ≈ 1,2 км ·
        сегодня 18:00–21:00», «Откликов 3 из 5 · подписка «Мастер на час»»."""
        headline = " · ".join(
            part for part in (_short(params.get("title")), self._budget(params, locale)) if part
        )
        where = ", ".join(part for part in (params.get("district"), self._distance(params)) if part)
        place = " · ".join(part for part in (where, self._when(params, locale)) if part)
        slots = self._t(
            "notifications.job_matched.slots",
            locale,
            count=params.get("responses", "0"),
            max=params.get("max_responses", "5"),
        )
        alert = params.get("alert")
        if alert:
            more = params.get("alert_more", "0")
            key = "alert_more" if more not in {"", "0"} else "alert"
            slots += " · " + self._t(
                f"notifications.job_matched.{key}", locale, alert=alert, count=more
            )
        return [headline, *([place] if place else []), slots]

    def _match_card(self, params: Mapping[str, str], locale: Locale) -> str:
        """HTML карточки B1: заголовок и название заявки жирным, остальное — как в тексте."""
        title = _short(params.get("title"))
        _, *lines = self._match_lines(params, locale)
        budget = self._budget(params, locale)
        headline = f"<b>{_escape(title)}</b>" + (f" · {_escape(budget)}" if budget else "")
        body = "\n".join([headline, *(_escape(line) for line in lines)])
        return f"<b>{_escape(self._match_title(params, locale))}</b>\n{body}"

    def _budget(self, params: Mapping[str, str], locale: Locale) -> str:
        """«5 000 RSD», «3 000–5 000 RSD в час», «Договорная»."""
        return budget(
            self._translator,
            locale,
            kind=params.get("budget_type"),
            low=_amount(params.get("budget_min")),
            high=_amount(params.get("budget_max")),
            unit=params.get("budget_unit"),
        )

    @staticmethod
    def _distance(params: Mapping[str, str]) -> str | None:
        """«≈ 1,2 км» или «≈ 800 м»: расстояние уже округлено до 100 м."""
        meters = params.get("distance_m", "")
        if not meters.isdigit():
            return None
        value = int(meters)
        if value < KM:
            return f"≈\u00a0{value}\u00a0м"
        km = f"{value / KM:.1f}".rstrip("0").rstrip(".").replace(".", ",")
        return f"≈\u00a0{km}\u00a0км"

    def _when(self, params: Mapping[str, str], locale: Locale) -> str | None:
        """Когда нужно: «сегодня 18:00–21:00», «завтра 10:00», «12 окт.», иначе по срочности —
        «срочно», «на этой неделе»."""
        start, end = params.get("from"), params.get("to")
        return when(
            self._translator,
            locale,
            start=datetime.fromisoformat(start) if start else None,
            end=datetime.fromisoformat(end) if end else None,
            urgency=params.get("urgency"),
            now=self._clock.now(),
        )

    def _match_buttons(
        self, params: Mapping[str, str], link: str | None, locale: Locale
    ) -> tuple[ButtonLine, ...]:
        """B1: «Открыть заявку» (S15), «Откликнуться шаблоном «…»» на каждый шаблон получателя
        (тот же отклик, что S16), одним рядом — «Не подходит» и «Пауза подписки»."""
        lines: list[ButtonLine] = []
        if link is not None and self._mini_app is not None:
            lines.append(
                AppButton(
                    text=self._t("notifications.job_matched.open", locale),
                    url=mini_app_url(self._mini_app, link),
                )
            )
        try:
            job_id = UUID(params.get("job_id", ""))
        except ValueError:
            return tuple(lines)
        for index in range(TEMPLATE_BUTTONS):
            try:
                template_id = UUID(params.get(f"template_{index}", ""))
            except ValueError:
                continue
            lines.append(
                CallbackButton(
                    text=self._t(
                        "notifications.job_matched.template",
                        locale,
                        title=params.get(f"template_{index}_title", ""),
                    ),
                    data=encode_callback(
                        CallbackData(CallbackAction.JOB_RESPOND, job_id, ref_arg(template_id))
                    ),
                )
            )
        row: list[Button] = [
            CallbackButton(
                text=self._t("notifications.job_matched.hide", locale),
                data=encode_callback(CallbackData(CallbackAction.JOB_HIDE, job_id)),
            )
        ]
        try:
            alert_id = UUID(params.get("alert_id", ""))
        except ValueError:
            pass
        else:
            row.append(
                CallbackButton(
                    text=self._t("notifications.job_matched.pause", locale),
                    data=encode_callback(CallbackData(CallbackAction.ALERT_PAUSE, alert_id)),
                )
            )
        lines.append(tuple(row))
        return tuple(lines)

    def _digest(self, params: Mapping[str, str], locale: Locale) -> RenderedText:
        """Подборка: одна подписка — одной фразой, несколько — итог и строка на каждую."""
        lines = [
            (params[f"alert_{index}"], params.get(f"alert_{index}_count", "0"))
            for index in range(DIGEST_LINES)
            if params.get(f"alert_{index}")
        ]
        title = self._t("notifications.job_digest.title", locale)
        if len(lines) == 1:
            (alert, count), *_ = lines
            body = self._t("notifications.job_digest.body_one", locale, alert=alert, count=count)
            return RenderedText(title=title, body=body)
        total = sum(int(count) for _, count in lines if count.isdigit())
        body = "\n".join(
            [
                self._t("notifications.job_digest.body_many", locale, count=total),
                *(
                    self._t("notifications.job_digest.line", locale, alert=alert, count=count)
                    for alert, count in lines
                ),
            ]
        )
        return RenderedText(title=title, body=body)

    def _stale_buttons(self, locale: Locale) -> tuple[ButtonLine, ...]:
        """«Включить «Доступен сегодня»» (S38) и «Обновить профиль» (кабинет S33)."""
        if self._mini_app is None:
            return ()
        return (
            AppButton(
                text=self._t("notifications.profile_stale_reminder.available", locale),
                url=mini_app_url(self._mini_app, AVAILABILITY_LINK),
            ),
            AppButton(
                text=self._t("notifications.profile_stale_reminder.profile", locale),
                url=mini_app_url(self._mini_app, CABINET_LINK),
            ),
        )

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

    def _marked_done(self, by: str, params: Mapping[str, str], locale: Locale) -> RenderedText:
        """B2 после отметки второй стороны: «Алексей: работа «…» выполнена. Всё в порядке?» — имя
        того, кто отметил, без согласования по роду. Имени нет (удалён аккаунт, уведомление до
        имени в параметрах) — роль: «Исполнитель: работа …»."""
        name = (params.get("name") or "").strip()
        if not name:
            name = self._t(f"notifications.deal_completion_prompt.name_{by}", locale)
        return RenderedText(
            title=self._t("notifications.deal_completion_prompt.title", locale),
            body=self._t(
                f"notifications.deal_completion_prompt.body_marked_{by}",
                locale,
                name=_short(name),
                title=_short(params.get("title")),
            ),
        )

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

    def _dispute_opened(self, params: Mapping[str, str], locale: Locale) -> RenderedText:
        """«Клиент сообщил о проблеме со сделкой «…»: не пришёл» и срок ответа."""
        by = "client" if params.get("by") == "client" else "performer"
        kind = params.get("kind", "other")
        kind = kind if kind in DISPUTE_KINDS else "other"
        lines = [
            self._t(
                f"notifications.dispute_opened.body_{by}",
                locale,
                title=_short(params.get("title")),
                kind=self._t(f"notifications.dispute_kind.{kind}", locale),
            )
        ]
        if until := params.get("until"):
            lines.append(
                self._t(
                    "notifications.dispute_opened.deadline",
                    locale,
                    when=self._datetime(until, locale),
                )
            )
        return RenderedText(
            title=self._t("notifications.dispute_opened.title", locale), body="\n".join(lines)
        )

    def _dispute_resolved(self, params: Mapping[str, str], locale: Locale) -> RenderedText:
        """Statement of reasons: что решила поддержка и почему; незнакомый код причины —
        общими словами."""
        outcome = params.get("outcome", "")
        outcome = outcome if outcome in DISPUTE_OUTCOMES else "cancelled"
        reason = self._first(
            locale,
            f"notifications.dispute_reason.{params.get('reason', 'other')}",
            "notifications.dispute_reason.other",
        )
        return RenderedText(
            title=self._t("notifications.dispute_resolved.title", locale),
            body=self._t(
                f"notifications.dispute_resolved.body_{outcome}",
                locale,
                title=_short(params.get("title")),
                reason=reason,
            ),
        )

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
        return price(self._translator, locale, price_type, _amount(amount))

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
        проблема» — сразу спор S52 в Mini App (`p_`, 6.1c), без лишнего шага через сделку."""
        buttons: list[Button] = []
        try:
            deal_id = UUID(params.get("deal_id", ""))
        except ValueError:
            deal_id = None
        if deal_id is not None:
            buttons.append(
                CallbackButton(
                    text=self._t("notifications.deal_completion_prompt.yes", locale),
                    data=encode_callback(CallbackData(CallbackAction.DEAL_COMPLETE, deal_id)),
                )
            )
        problem = (
            encode_start_param(StartLink(type=LinkType.DISPUTE, id=deal_id))
            if deal_id is not None
            else link
        )
        if problem is not None and self._mini_app is not None:
            buttons.append(
                AppButton(
                    text=self._t("notifications.deal_completion_prompt.problem", locale),
                    url=mini_app_url(self._mini_app, problem),
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
        if entity == "appeal":
            return self._appeal_decided(params, locale)
        code = params.get("decision_code") or "other"
        if code in PROHIBITED:
            code = "prohibited"
        reason = self._first(
            locale,
            f"notifications.moderation_reason.{code}",
            "notifications.moderation_reason.other",
        )
        # спор (6.1c): исправлять нечего — «поддержка нашла нарушение», а не «исправьте»
        body = "body_dispute" if entity == "dispute" else "body"
        parts = [self._t(f"notifications.moderation_decision.{body}", locale, reason=reason)]
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

    def _appeal_decided(self, params: Mapping[str, str], locale: Locale) -> RenderedText:
        """Итог апелляции (2.5b): санкция снята — или решение в силе, с причиной."""
        if params.get("appeal") == "granted":
            return RenderedText(
                title=self._t("notifications.appeal_decided.title.granted", locale),
                body=self._t("notifications.appeal_decided.body.granted", locale),
            )
        code = params.get("decision_code") or "other"
        reason = self._first(
            locale,
            f"notifications.appeal_reason.{code}",
            "notifications.appeal_reason.other",
        )
        return RenderedText(
            title=self._t("notifications.appeal_decided.title.denied", locale),
            body=self._t("notifications.appeal_decided.body.denied", locale, reason=reason),
        )

    def _t(self, key: str, locale: Locale, **params: object) -> str:
        """Текст ключа; ключа нет ни в одном каталоге — сам ключ (пропуск виден в тесте)."""
        return self._translator.text(key, locale, **params) or key

    def _first(self, locale: Locale, key: str, fallback: str) -> str:
        """Текст ключа или запасного: коды причин и видов контента открыты для модерации."""
        return self._translator.text(key, locale) or self._t(fallback, locale)

    def _datetime(self, value: str, locale: Locale) -> str:
        """Дата и время по Белграду в формате языка: «12 октября 2026 г., 08:30». Во всех шаблонах
        она после «до» или значит «когда» — сербский месяц в родительном («do 12. oktobra»)."""
        return long_datetime(datetime.fromisoformat(value), locale, genitive=True)


def _escape(text: str) -> str:
    return html.escape(text, quote=False)


def _amount(value: str | None) -> int | None:
    """Сумма из параметров (пара строкой); нет или не число — None."""
    return int(value) if value is not None and value.isdigit() else None


def _short(title: str | None) -> str:
    title = (title or "").strip()
    return title if len(title) <= TITLE_CHARS else title[: TITLE_CHARS - 1].rstrip() + "…"
