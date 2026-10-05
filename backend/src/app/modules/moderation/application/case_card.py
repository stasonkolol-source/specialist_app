"""Карточка кейса в чате модераторов (DEVELOPMENT_PLAN 2.5b; ARCHITECTURE §14.1, ADR-0016 §4):
текст и кнопки — для отправки (infrastructure/chat.py) и правки ботом (bot/handlers.py).

Закрытый Telegram-чат модераторов (K29): бот присылает туда карточку каждого нового кейса — все
очереди, споры и апелляции. По карточке модератор решает с телефона (отзыв владельца
2026-10-05: от карточки с одними id пользы мало):
- заголовок — приоритет, очередь и что случилось словами: «P2 · Премодерация · новый профиль на
  проверку»;
- кто — публичное имя, как его показывает приложение («Алексей М.»), роль (клиент, специалист и
  основная категория) и район; строкой ниже — сколько он в сервисе, уровень доверия, завершённые
  сделки и жалобы на него (открытые из всех);
- что — объект словами и сам проверяемый текст, обрезанный до ~400 символов: у профиля —
  «коротко о себе» и «о себе», у заявки — название, описание и бюджет, у отзыва — оценка и
  текст, у сообщения — только оно само;
- почему — повод и сигналы словами: контакты в «О себе», просьба о предоплате, стоп-правило,
  категории фото с оценками, «новый профиль — всегда человек», причина жалобы и роль
  жалующегося (его текст — только короткий: это тоже пользовательский контент);
- срок по SLA: «до 17:43 (через 2 ч)».
Кейс о фото (фото профиля, работа портфолио, фото заявки — всё это публично в приложении)
приходит самим фото (вариант `md` без EXIF) с карточкой в подписи. Фото, скрытое автоматически
(P0), в чат не уходит: «скрыто автоматически — смотреть в админке».

Граница приватности. В карточке никогда нет телефонов, Telegram-username и id пользователей,
точных адресов, переписки целиком, файлов-доказательств спора и вообще ничего вне объекта кейса.
Контакты в самом проверяемом тексте замаскированы («•••», как для внешнего AI): что нашлось и
где — сказано в «почему». У спора — название сделки, публичные имена сторон, вид спора и «N фото —
в админке» (просмотр доказательств пишется в audit_log); у апелляции — какое решение обжалуют
(своего текста у апелляции нет). Пользовательский текст экранируется (HTML); длина — в пределах
Bot API (текст ≤ 4096, подпись к фото ≤ 1024 символов) с запасом под строки итога решения.

Кнопки (callbacks.py): «Одобрить», «Отклонить с причиной» (выбор причины, затем тяжести —
лестница санкций), «Эскалировать»; у спора — «Выполнено» и «Отменить с причиной», у апелляции
«Одобрить» снимает санкцию, а причина отказа — без санкции. Нажатие обрабатывает бот модуля
(moderation/bot/handlers.py) тем же use case, что `cli`: DecideCase, ResolveDispute,
EscalateCase. Под ними — ссылка «Открыть в админке» на страницу кейса (`/admin/decide-case`):
кнопкой, если адрес админки публичный; локальный адрес dev (127.0.0.1) Telegram в кнопке не
примет — тогда строкой в тексте. Тексты — на языке чата модераторов (`MODERATORS_LOCALE`).

Чат не задан (`TELEGRAM_MODERATORS_CHAT_ID` пусто) — карточек нет, кейсы решают командами `cli`.
"""

import html
import ipaddress
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Final
from urllib.parse import urlencode, urlsplit

from app.modules.moderation.application.dto import CaseContext, ContentField, PersonContext
from app.modules.moderation.domain.cases import Case, CaseTrigger, EntityType
from app.modules.moderation.domain.sanctions import Severity
from app.platform.i18n.jobs import budget
from app.platform.i18n.translator import Translator
from app.platform.kernel.clock import BUSINESS_TZ
from app.platform.kernel.ids import CaseId
from app.platform.kernel.localized import Locale
from app.platform.telegram.callbacks import CallbackAction, CallbackData, encode_callback
from app.platform.telegram.port import ButtonLine, CallbackButton, InactiveButton, LinkButton
from app.platform.text.contact_masking import find_contacts, mask_contacts

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

TEXT_LIMIT: Final = 4096
CAPTION_LIMIT: Final = 1024
"""Пределы Bot API в символах после разбора разметки (UTF-16): текст и подпись к фото."""
OUTCOME_RESERVE: Final = 200
"""Запас под строки итога: бот дописывает к карточке «эскалировано», потом решение."""
CONTENT_CHARS: Final = 400
"""Проверяемый текст в карточке — не длиннее (по всем полям вместе); целиком — в админке."""
COMMENT_CHARS: Final = 200
"""Текст жалобы — в карточку, только если не длиннее: это тоже пользовательский контент."""
PATTERN_CHARS: Final = 40
"""Шаблон стоп-правила в «почему» — обрезанный: регулярка бывает длинной."""
MAX_REASONS: Final = 8
MAX_REPORTS: Final = 3
ADMIN_CASE_PAGE: Final = "/decide-case"
"""Страница кейса в админке (2.7b): решение, а у спора — и доказательства (с записью в аудит)."""

_TAG: Final = re.compile(r"<[^>]*>")
_MANUAL_IMAGES: Final = frozenset({"image:unavailable:no_key", "image:unavailable:not_configured"})
"""Фото без автопроверки по решению (ключа AI нет): это не сбой, а обычная ручная проверка."""
_DUPLICATE: Final = "portfolio_duplicate"


def reasons_for(case: Case) -> tuple[str, ...]:
    if case.is_appeal:
        return APPEAL_REASONS
    if case.entity_type is EntityType.DISPUTE:
        return DISPUTE_REASONS
    return CONTENT_REASONS


def card_text(
    case: Case,
    context: CaseContext,
    translator: Translator,
    *,
    now: datetime,
    admin_url: str | None = None,
    limit: int = TEXT_LIMIT - OUTCOME_RESERVE,
) -> str:
    """Текст карточки (HTML, пользовательское экранировано) не длиннее `limit` видимых символов:
    не влезает — короче проверяемый текст, потом меньше поводов. `admin_url` — адрес админки:
    непубличный (dev) выводится строкой, публичный — кнопкой (`card_buttons`)."""
    text = ""
    for content_chars in (CONTENT_CHARS, CONTENT_CHARS // 2, CONTENT_CHARS // 4, 0):
        for max_reasons in (MAX_REASONS, 3, 1):
            text = _render(
                case,
                context,
                _Texts(translator),
                now=now,
                admin_url=admin_url,
                content_chars=content_chars,
                max_reasons=max_reasons,
            )
            if visible_length(text) <= limit:
                return text
    return text


def card_caption(
    case: Case,
    context: CaseContext,
    translator: Translator,
    *,
    now: datetime,
    admin_url: str | None = None,
) -> str:
    """Карточка подписью к фото: предел Bot API для подписи — 1024 символа."""
    return card_text(
        case,
        context,
        translator,
        now=now,
        admin_url=admin_url,
        limit=CAPTION_LIMIT - OUTCOME_RESERVE,
    )


def card_buttons(
    case: Case, translator: Translator, admin_url: str | None = None
) -> tuple[ButtonLine, ...]:
    """Кнопки карточки: у спора исход сделки, у остальных — одобрить или отклонить; ниже —
    «Открыть в админке», если адрес админки публичный."""
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
        *admin_buttons(case.id, translator, admin_url),
    )


def admin_buttons(
    case_id: CaseId, translator: Translator, admin_url: str | None
) -> tuple[ButtonLine, ...]:
    """Кнопка «Открыть в админке» — остаётся и под решённой карточкой; адрес непубличный
    (dev: Telegram отвергнет кнопку на 127.0.0.1) — кнопки нет, ссылка строкой в тексте."""
    if admin_url is None or not public_url(admin_url):
        return ()
    label = plain_text(translator, "bot.moderation.button.admin", MODERATORS_LOCALE)
    return (LinkButton(text=label, url=admin_case_url(admin_url, case_id)),)


def superseded_buttons(
    case_id: CaseId, translator: Translator, admin_url: str | None
) -> tuple[ButtonLine, ...]:
    """Под карточкой устаревшего кейса (объект изменили после неё, ADV-11) кнопок решения нет:
    неактивная строка «Версия изменилась — смотрите новую карточку» и «Открыть в админке»."""
    label = plain_text(translator, "bot.moderation.superseded", MODERATORS_LOCALE)
    return (InactiveButton(text=label), *admin_buttons(case_id, translator, admin_url))


def admin_case_url(admin_url: str, case_id: CaseId) -> str:
    return f"{admin_url.rstrip('/')}{ADMIN_CASE_PAGE}?{urlencode({'case_id': str(case_id)})}"


def public_url(url: str) -> bool:
    """Адрес, который Telegram примет в кнопке: http(s) с доменом или публичным IP, не
    localhost и не адрес локальной сети."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme not in {"http", "https"} or not host or host == "localhost":
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return "." in host


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


def visible_length(text: str) -> int:
    """Длина HTML-текста, как её считает Bot API: без тегов, сущности раскрыты, в UTF-16."""
    plain = html.unescape(_TAG.sub("", text))
    return len(plain.encode("utf-16-le")) // 2


def clip(text: str, limit: int) -> str:
    """Текст одной строкой, не длиннее `limit` символов: дальше — «…» (по границе слова)."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    if limit <= 1:
        return "…"
    cut = flat[: limit - 1]
    if not flat[limit - 1].isspace():  # слово разрезано — до предыдущего пробела
        space = cut.rfind(" ")
        if space >= limit // 2:
            cut = cut[:space]
    return cut.rstrip(" ,.;:—-") + "…"


class _Texts:
    """Тексты карточки на языке чата модераторов: `t` — шаблон с экранированными параметрами,
    `word` — подпись без разметки, `first` — первый ключ, который есть в каталоге."""

    def __init__(self, translator: Translator) -> None:
        self._translator = translator

    def t(self, key: str, **params: object) -> str:
        return html_text(self._translator, key, MODERATORS_LOCALE, **params)

    def word(self, key: str, fallback: str | None = None, **params: object) -> str:
        """Простой текст (станет параметром другого шаблона и экранируется там)."""
        found = self._translator.text(key, MODERATORS_LOCALE, **params)
        return found if found else (fallback if fallback is not None else key)

    def first(self, *keys: str, **params: object) -> str:
        for key in keys:
            if self._translator.text(key, MODERATORS_LOCALE) is not None:
                return self.t(key, **params)
        return self.t(keys[-1], **params)

    @property
    def translator(self) -> Translator:
        return self._translator


def _render(
    case: Case,
    context: CaseContext,
    texts: _Texts,
    *,
    now: datetime,
    admin_url: str | None,
    content_chars: int,
    max_reasons: int,
) -> str:
    t = texts.t
    queue = texts.word(f"bot.moderation.queue.{case.queue.value}", case.queue.value)
    header = t("bot.moderation.card.header", queue=queue, event=_event(case, context, texts))
    who = _who(context.subject, texts, now=now)
    what = _what(context, texts, content_chars=content_chars)
    reasons = _reasons(case, context, texts)
    why = [f"{t('bot.moderation.card.why')} {'; '.join(reasons[:max_reasons])}"] if reasons else []
    tail = [t("bot.moderation.card.due", due=_due(case.due_at, now), left=_left(case, now, texts))]
    if admin_url is not None and not public_url(admin_url):
        tail.append(t("bot.moderation.card.admin_link", url=admin_case_url(admin_url, case.id)))
    tail.append(t("bot.moderation.card.case", case_id=case.id))
    sections = (header, "\n".join(who), "\n".join(what), "\n".join([*why, *tail]))
    return "\n\n".join(section for section in sections if section)


def _event(case: Case, context: CaseContext, texts: _Texts) -> str:
    """Что случилось — словами, для заголовка."""
    signals = _all_signals(case)
    entity = case.entity_type.value
    match case.trigger:
        case CaseTrigger.NEW_CONTENT:
            return texts.first(f"bot.moderation.event.new.{entity}", "bot.moderation.event.new")
        case CaseTrigger.EDIT:
            return texts.t("bot.moderation.event.edit")
        case CaseTrigger.REPORT:
            return texts.t("bot.moderation.event.report")
        case CaseTrigger.APPEAL:
            return texts.t("bot.moderation.event.appeal")
        case CaseTrigger.DISPUTE:
            return texts.t("bot.moderation.event.dispute")
    if case.entity_type is EntityType.MEDIA:
        if context.photo_hidden:
            return texts.t("bot.moderation.event.photo_hidden")
        if any(signal in _MANUAL_IMAGES for signal in signals):
            return texts.t("bot.moderation.event.photo_review")  # MVP без ключа AI: всё — человеку
        if any(s == "image:unchecked" or s.startswith("image:unavailable") for s in signals):
            return texts.t("bot.moderation.event.photo_unchecked")
        return texts.t("bot.moderation.event.photo_flagged")
    if _DUPLICATE in signals:
        return texts.t("bot.moderation.event.duplicate")
    if any(_is_block(signal) for signal in signals):
        return texts.t("bot.moderation.event.blocked")
    for signal in ("sample", "demo"):
        if signal in signals:
            return texts.t(f"bot.moderation.event.{signal}")
    return texts.t("bot.moderation.event.auto_flag")


def _who(person: PersonContext, texts: _Texts, *, now: datetime) -> list[str]:
    """Кто: имя, роль, район; ниже — сколько в сервисе, доверие, сделки и жалобы."""
    t = texts.t
    if person.name is None:
        lines = [t("bot.moderation.card.who_deleted")]
    else:
        role = _role(person.role, person.category, texts)
        if person.district:
            line = t(
                "bot.moderation.card.who_in", name=person.name, role=role, area=person.district
            )
        else:
            line = t("bot.moderation.card.who", name=person.name, role=role)
        lines = [line]
    facts = []
    if person.joined_at is not None:
        facts.append(t("bot.moderation.card.age", age=_age(now - person.joined_at, texts)))
    if person.trust_level is not None:
        facts.append(t("bot.moderation.card.trust", level=person.trust_level))
    if person.deals_done is not None:
        facts.append(t("bot.moderation.card.deals", count=person.deals_done))
    facts.append(
        t(
            "bot.moderation.card.complaints",
            open=person.complaints_open,
            total=person.complaints_total,
        )
    )
    lines.append(" · ".join(facts))
    return lines


def _role(role: str, category: str | None, texts: _Texts) -> str:
    """Клиент, специалист или подработка — с основной категорией, если она есть."""
    if role == "client":
        return texts.word("bot.moderation.role.client", role)
    label = texts.word(f"bot.moderation.role.{role}", role)
    if category is None:
        return label
    return texts.word(
        "bot.moderation.role.with_category", f"{label}: {category}", role=label, category=category
    )


def _what(context: CaseContext, texts: _Texts, *, content_chars: int) -> list[str]:
    """Что: объект словами и проверяемый текст (контакты замаскированы, обрезан)."""
    t, found = texts.t, context.object
    name = texts.word(f"bot.moderation.object.{found.kind}", found.kind)
    lines = [
        t(
            "bot.moderation.card.what_missing" if found.missing else "bot.moderation.card.what",
            object=name,
        )
    ]
    if context.dispute is not None:
        dispute = context.dispute
        lines.append(t("bot.moderation.card.deal", title=dispute.title or "—"))
        lines.append(
            t(
                "bot.moderation.card.parties",
                opened=dispute.opened_by or texts.word("bot.moderation.card.deleted"),
                respondent=dispute.respondent or texts.word("bot.moderation.card.deleted"),
            )
        )
        if dispute.photos:
            lines.append(t("bot.moderation.card.dispute_photos", count=dispute.photos))
    if found.rating is not None:
        stars = "★" * found.rating + "☆" * max(0, 5 - found.rating)
        lines.append(_field(texts, "rating", stars))
    left = content_chars
    for field in found.fields:
        if left <= 0:
            break
        text = clip(mask_contacts(field.text), left)
        left -= len(text)
        lines.append(_field(texts, field.name, text))
    if found.budget is not None:
        amount = budget(
            texts.translator,
            MODERATORS_LOCALE,
            kind=found.budget.kind,
            low=found.budget.low,
            high=found.budget.high,
            unit=found.budget.unit,
        )
        lines.append(_field(texts, "budget", amount))
    if context.photo_hidden:
        lines.append(t("bot.moderation.card.photo_hidden"))
    return lines


def _field(texts: _Texts, name: str, text: str) -> str:
    label = texts.word(f"bot.moderation.field.{name}", name)
    return texts.t("bot.moderation.card.field", label=label, text=text)


def _reasons(case: Case, context: CaseContext, texts: _Texts) -> list[str]:
    """Почему: поводы и сигналы словами, по порядку, без повторов."""
    t = texts.t
    found: list[str] = []
    if context.appeal is not None or case.appeal_of is not None:
        code = context.appeal.reason_code if context.appeal is not None else None
        code = code or next(
            (str(e["reason_code"]) for e in case.evidence if e.get("reason_code")), ""
        )
        decided = context.appeal.decided_at if context.appeal is not None else None
        reason = _reason_word(code, texts)
        if decided is not None:
            found.append(t("bot.moderation.why.appeal_from", reason=reason, date=_date(decided)))
        else:
            found.append(t("bot.moderation.why.appeal", reason=reason))
    for report in context.reports[:MAX_REPORTS]:
        reason = texts.word(f"bot.moderation.report.{report.reason}", report.reason)
        if report.reporter_role is not None:
            who = texts.word(
                f"bot.moderation.reporter.{report.reporter_role}", report.reporter_role
            )
            line = t("bot.moderation.why.report_by", reason=reason, reporter=who)
        else:
            line = t("bot.moderation.why.report", reason=reason)
        comment = " ".join((report.comment or "").split())
        if comment and len(comment) <= COMMENT_CHARS:
            line += " " + t("bot.moderation.why.comment", comment=mask_contacts(comment))
        found.append(line)
    places = _contact_places(context.object.fields, texts)
    for signal in _all_signals(case):
        phrase = _signal(signal, case, texts, places=places, reported=bool(context.reports))
        if phrase and phrase not in found:
            found.append(phrase)
    return found


def _signal(signal: str, case: Case, texts: _Texts, *, places: str, reported: bool) -> str | None:
    """Сигнал словами; неизвестный — как есть (экранированным)."""
    t = texts.t
    head, _, rest = signal.partition(":")
    simple: Mapping[str, Callable[[], str]] = {
        "risky_category": lambda: t("bot.moderation.why.risky_category"),
        "sample": lambda: t("bot.moderation.why.sample"),
        "demo": lambda: t("bot.moderation.why.demo"),
        "always_review": lambda: texts.first(
            f"bot.moderation.why.always_review.{case.entity_type.value}",
            "bot.moderation.why.always_review",
        ),
        _DUPLICATE: lambda: t("bot.moderation.why.duplicate", count=_duplicates(case)),
    }
    if signal in simple:
        return simple[signal]()
    match head:
        case "appeal":
            return None  # обжалованное решение — строкой выше
        case "report":
            if reported:
                return None  # жалобы — с ролью и текстом, строками выше
            return t(
                "bot.moderation.why.report",
                reason=texts.word(f"bot.moderation.report.{rest}", rest),
            )
        case "rule" | "velocity" | "detector":
            return _rule(head, rest, texts, places=places)
        case "omni":
            if rest.startswith("unavailable"):
                return t("bot.moderation.why.omni_unavailable")
            return t("bot.moderation.why.omni", category=rest)
        case "classifier":
            return _classifier(rest, texts)
        case "image":
            return _image(rest, texts)
        case "dispute":
            if rest in {"answered", "no_response"}:
                return t(f"bot.moderation.why.dispute_{rest}")
            return t(
                "bot.moderation.why.dispute",
                kind=texts.word(f"bot.moderation.dispute.{rest}", rest),
            )
    return html.escape(signal, quote=False)


def _rule(source: str, rest: str, texts: _Texts, *, places: str) -> str:
    """Сработавшее правило: `<категория>:<действие>:<что совпало>` (domain/pipeline.py)."""
    t = texts.t
    category, _, tail = rest.partition(":")
    action, _, evidence = tail.partition(":")
    if source == "velocity":
        return t("bot.moderation.why.velocity", evidence=evidence)
    if source == "detector" and category == "contacts":
        kinds = ", ".join(
            texts.word(f"bot.moderation.contact.{kind.strip()}", kind.strip())
            for kind in evidence.split(",")
            if kind.strip()
        )
        if places:
            return t("bot.moderation.why.contacts_in", kinds=kinds, field=places)
        return t("bot.moderation.why.contacts", kinds=kinds)
    if source == "detector" and category == "scam":
        return t("bot.moderation.why.prepayment")
    key = "bot.moderation.why.rule_block" if action == "block" else "bot.moderation.why.rule"
    label = texts.word(f"bot.moderation.category.{category}", category)
    return t(key, pattern=clip(evidence, PATTERN_CHARS), category=label)


def _classifier(rest: str, texts: _Texts) -> str:
    t = texts.t
    label, _, confidence = rest.partition(":")
    if label == "unavailable":
        return t("bot.moderation.why.classifier_unavailable")
    if label == "unsure":
        return t("bot.moderation.why.classifier_unsure", confidence=confidence)
    return t(
        "bot.moderation.why.classifier", label=_reason_word(label, texts), confidence=confidence
    )


def _image(rest: str, texts: _Texts) -> str:
    """Сигнал фото (domain/images.py): категория omni с оценкой или «проверка не состоялась»."""
    t = texts.t
    if f"image:{rest}" in _MANUAL_IMAGES:
        return t("bot.moderation.why.image_manual")
    if rest == "unchecked" or rest.startswith("unavailable"):
        return t("bot.moderation.why.image_unchecked")
    if rest == "flagged":
        return t("bot.moderation.why.image_flagged")
    category, _, score = rest.rpartition(":")
    key = re.sub(r"[^a-z]+", "_", category)
    label = texts.word(f"bot.moderation.image.{key}", category)
    return t("bot.moderation.why.image", category=label, score=score)


def _contact_places(fields: Sequence[ContentField], texts: _Texts) -> str:
    """Где в тексте контакты: подписи полей («О себе») — до маскировки."""
    return ", ".join(
        f"«{texts.word(f'bot.moderation.field.{field.name}', field.name)}»"
        for field in fields
        if find_contacts(field.text)
    )


def _reason_word(code: str, texts: _Texts) -> str:
    return texts.word(f"bot.moderation.reason.{code}", code) if code else "—"


def _duplicates(case: Case) -> int:
    return sum(
        len(matches) for entry in case.evidence if isinstance(matches := entry.get("matches"), list)
    )


def _is_block(signal: str) -> bool:
    parts = signal.split(":", 3)
    return len(parts) == 4 and parts[0] in {"rule", "velocity"} and parts[2] == "block"


def _all_signals(case: Case) -> list[str]:
    found: dict[str, None] = {}
    for entry in case.evidence:
        signals = entry.get("signals")
        if isinstance(signals, list):
            found.update(dict.fromkeys(str(signal) for signal in signals))
    return list(found)


def _age(age: timedelta, texts: _Texts) -> str:
    if age < timedelta(days=1):
        return texts.t("bot.moderation.card.hours", count=max(0, int(age.total_seconds() // 3600)))
    return texts.t("bot.moderation.card.days", count=age.days)


def _left(case: Case, now: datetime, texts: _Texts) -> str:
    """Сколько осталось до срока: «через 2 ч», «через 25 мин», «просрочено»."""
    left = case.due_at - now
    minutes = int(left.total_seconds() // 60)
    if minutes <= 0:
        return texts.t("bot.moderation.left.overdue")
    if minutes < 60:
        return texts.t("bot.moderation.left.minutes", count=minutes)
    if left < timedelta(days=2):
        return texts.t("bot.moderation.left.hours", count=max(1, round(minutes / 60)))
    return texts.t("bot.moderation.left.days", count=left.days)


def _due(moment: datetime, now: datetime) -> str:
    """Срок по Белграду: сегодня — только время, иначе дата и время."""
    local = moment.astimezone(BUSINESS_TZ)
    if local.date() == now.astimezone(BUSINESS_TZ).date():
        return f"{local:%H:%M}"
    return f"{local:%d.%m %H:%M}"


def _date(moment: datetime) -> str:
    return f"{moment.astimezone(BUSINESS_TZ):%d.%m.%Y}"


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
