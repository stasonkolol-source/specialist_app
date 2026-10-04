"""Карточка кейса в чате модераторов (DEVELOPMENT_PLAN 2.5b; ARCHITECTURE §14.1, ADR-0016 §4):
текст и кнопки — для отправки (infrastructure/chat.py) и правки ботом (bot/handlers.py).

Закрытый Telegram-чат модераторов (K29): бот присылает туда карточку каждого нового кейса —
все очереди, споры и апелляции. Карточка компактная и без контактов: очередь, объект и
пользователь — псевдонимными id, повод и сигналы, срок по SLA. У спора — сколько фото, а
смотреть их — `cli dispute-show` (ссылки на 5 минут, просмотр пишется в audit_log); у
апелляции — какое решение обжалуют.

Кнопки (callbacks.py): «Одобрить», «Отклонить с причиной» (выбор причины, затем тяжести —
лестница санкций), «Эскалировать»; у спора — «Выполнено» и «Отменить с причиной», у апелляции
«Одобрить» снимает санкцию, а причина отказа — без санкции. Нажатие обрабатывает бот модуля
(moderation/bot/handlers.py) тем же use case, что `cli`: DecideCase, ResolveDispute,
EscalateCase. Тексты — на языке чата модераторов (`MODERATORS_LOCALE`).

Чат не задан (`TELEGRAM_MODERATORS_CHAT_ID` пусто) — карточек нет, кейсы решают командами `cli`.
"""

import html
from collections.abc import Sequence
from datetime import datetime
from typing import Final

from app.modules.moderation.domain.cases import Case, EntityType
from app.modules.moderation.domain.sanctions import Severity
from app.platform.i18n.translator import Translator
from app.platform.kernel.clock import BUSINESS_TZ
from app.platform.kernel.ids import CaseId
from app.platform.kernel.localized import Locale
from app.platform.telegram.callbacks import CallbackAction, CallbackData, encode_callback
from app.platform.telegram.port import ButtonLine, CallbackButton

MODERATORS_LOCALE: Final = Locale.RU
"""Язык чата модераторов: команда говорит по-русски (Q21); другой — ключом настроек позже."""

CONTENT_REASONS: Final = (
    "prepayment_scam",
    "off_platform_payment",
    "contact_leak",
    "spam_ad",
    "prohibited",
    "mule_recruitment",
    "not_a_service_request",
    "vacancy",
    "other",
)
"""Причины отказа по контенту, жалобе и аккаунту — коды ADR-0016 (statement of reasons)."""
DISPUTE_REASONS: Final = (
    "not_done",
    "no_show",
    "poor_quality",
    "prepayment_scam",
    "mutual",
    "other",
)
"""Причины отмены сделки по спору (6.1c, `cli dispute-resolve … cancelled --reason`)."""
APPEAL_REASONS: Final = ("decision_upheld", "other")
"""Апелляция отклонена: решение остаётся в силе."""
DISPUTE_DONE_REASON: Final = "work_done"
"""«Выполнено» у спора: работа сделана, сделка завершается."""

SEVERITY_CODES: Final = {
    "n": None,
    "m": Severity.MINOR,
    "s": Severity.SERIOUS,
    "c": Severity.CRITICAL,
}
"""Первая буква аргумента CASE_SANCTION: тяжесть нарушения; `n` — без санкции."""
_MAX_SIGNALS: Final = 6


def reasons_for(case: Case) -> tuple[str, ...]:
    if case.is_appeal:
        return APPEAL_REASONS
    if case.entity_type is EntityType.DISPUTE:
        return DISPUTE_REASONS
    return CONTENT_REASONS


def card_text(case: Case, translator: Translator) -> str:
    """Текст карточки: HTML, параметры экранированы (texts.py)."""

    def t(key: str, **params: object) -> str:
        return html_text(translator, key, MODERATORS_LOCALE, **params)

    lines = [
        t("bot.moderation.card.title", queue=t(f"bot.moderation.queue.{case.queue.value}"))
        + f" <code>{case.id}</code>",
        t("bot.moderation.card.entity", entity=case.entity_type.value)
        + f" <code>{case.entity_id}</code>",
        t("bot.moderation.card.subject") + f" <code>{case.subject_id}</code>",
        t("bot.moderation.card.trigger", trigger=case.trigger.value),
    ]
    if signals := _signals(case):
        lines.append(t("bot.moderation.card.signals", signals=", ".join(signals)))
    if case.appeal_of is not None:
        reason = next(
            (str(e["reason_code"]) for e in case.evidence if e.get("reason_code")), "other"
        )
        lines.append(
            t("bot.moderation.card.appeal", reason=reason) + f" <code>{case.appeal_of}</code>"
        )
    if case.entity_type is EntityType.DISPUTE:
        lines.append(t("bot.moderation.card.photos", count=len(case.media_ids)))
        lines.append(f"<code>cli dispute-show {case.id} --by &lt;tg id&gt;</code>")
    lines.append(t("bot.moderation.card.due", due=_local(case.due_at)))
    return "\n".join(lines)


def card_buttons(case: Case, translator: Translator) -> tuple[ButtonLine, ...]:
    """Кнопки карточки: у спора исход сделки, у остальных — одобрить или отклонить."""
    dispute = case.entity_type is EntityType.DISPUTE and not case.is_appeal
    approve = "bot.moderation.button.dispute_done" if dispute else "bot.moderation.button.approve"
    reject = "bot.moderation.button.dispute_cancel" if dispute else "bot.moderation.button.reject"
    return (
        (
            _button(translator, approve, CallbackAction.CASE_APPROVE, case.id),
            _button(translator, reject, CallbackAction.CASE_REJECT, case.id),
        ),
        _button(
            translator, "bot.moderation.button.escalate", CallbackAction.CASE_ESCALATE, case.id
        ),
    )


def reason_buttons(case: Case, translator: Translator) -> tuple[ButtonLine, ...]:
    """Выбор причины отказа: коды — как в `cli` и statement of reasons."""
    codes = reasons_for(case)
    buttons = [
        CallbackButton(
            text=code, data=encode_callback(CallbackData(CallbackAction.CASE_REJECT, case.id, code))
        )
        for code in codes
    ]
    rows: list[ButtonLine] = [tuple(buttons[i : i + 2]) for i in range(0, len(buttons), 2)]
    rows.append(
        _button(translator, "bot.moderation.button.back", CallbackAction.CASE_BACK, case.id)
    )
    return tuple(rows)


def severity_buttons(
    case_id: CaseId, reason: str, translator: Translator
) -> tuple[ButtonLine, ...]:
    """Тяжесть нарушения — ступень лестницы санкций (domain/sanctions.py)."""
    rows: list[ButtonLine] = [
        CallbackButton(
            text=plain_text(
                translator, f"bot.moderation.severity.{_severity_name(code)}", MODERATORS_LOCALE
            ),
            data=encode_callback(
                CallbackData(CallbackAction.CASE_SANCTION, case_id, f"{code}{reason}")
            ),
        )
        for code in SEVERITY_CODES
    ]
    rows.append(
        _button(translator, "bot.moderation.button.back", CallbackAction.CASE_BACK, case_id)
    )
    return tuple(rows)


def outcome_line(translator: Translator, key: str, *, who: str, **params: object) -> str:
    """Строка итога под карточкой: что решили и кто (имя модератора из Telegram)."""
    return html_text(translator, key, MODERATORS_LOCALE, who=who, **params)


def html_text(translator: Translator, key: str, locale: Locale, **params: object) -> str:
    """Как platform/telegram/texts.py (без aiogram — слой application): шаблон — доверенный
    HTML, параметры экранируются."""
    safe = {name: html.escape(str(value), quote=False) for name, value in params.items()}
    return translator.text(key, locale, **safe) or key


def plain_text(translator: Translator, key: str, locale: Locale) -> str:
    """Подпись кнопки или ответ на нажатие — как есть, без разметки."""
    return translator.text(key, locale) or key


def _button(
    translator: Translator, key: str, action: CallbackAction, case_id: CaseId
) -> CallbackButton:
    return CallbackButton(
        text=plain_text(translator, key, MODERATORS_LOCALE),
        data=encode_callback(CallbackData(action, case_id)),
    )


def _severity_name(code: str) -> str:
    severity = SEVERITY_CODES[code]
    return severity.value if severity is not None else "none"


def _signals(case: Case) -> Sequence[str]:
    found: dict[str, None] = {}
    for entry in case.evidence:
        signals = entry.get("signals")
        if isinstance(signals, list):
            found.update(dict.fromkeys(str(signal) for signal in signals))
    return list(found)[:_MAX_SIGNALS]


def _local(moment: datetime) -> str:
    return f"{moment.astimezone(BUSINESS_TZ):%d.%m %H:%M}"
