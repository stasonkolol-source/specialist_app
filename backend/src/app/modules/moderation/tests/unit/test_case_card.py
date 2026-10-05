"""Карточка кейса в чате модераторов (DEVELOPMENT_PLAN 2.5b, отзыв владельца 2026-10-05): по
каждому виду объекта — что случилось, кто, что и почему словами; граница приватности (контакты
замаскированы, ни телефона, ни Telegram, ни id пользователя), обрезка под пределы Bot API,
экранирование пользовательского текста, ссылка на кейс в админке."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.moderation.application.case_card import (
    CAPTION_LIMIT,
    CONTENT_CHARS,
    OUTCOME_RESERVE,
    TEXT_LIMIT,
    admin_buttons,
    card_buttons,
    card_caption,
    card_text,
    clip,
    public_url,
    visible_length,
)
from app.modules.moderation.application.dto import (
    AppealContext,
    BudgetContext,
    CaseContext,
    CaseObject,
    ContentField,
    DisputeContext,
    PersonContext,
    ReportContext,
)
from app.modules.moderation.domain.cases import Case, CaseTrigger, EntityType
from app.modules.moderation.domain.queues import Queue
from app.platform.i18n.translator import Translator
from app.platform.kernel.ids import CaseId, MediaId, UserId, new_id
from app.platform.telegram.port import CallbackButton, LinkButton

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 5, 13, 43, tzinfo=UTC)  # 15:43 в Белграде
ADMIN = "https://admin.sosedi.example/admin"
DEV_ADMIN = "http://127.0.0.1:8000/admin"
SPECIALIST = PersonContext(
    name="Алексей М.",
    role="pro",
    category="Сантехника",
    district="Лиман",
    joined_at=NOW - timedelta(days=3),
    trust_level=0,
    deals_done=0,
)
CLIENT = PersonContext(
    name="Ирина С.",
    role="client",
    district="Детелинара",
    joined_at=NOW - timedelta(hours=5),
    trust_level=1,
    deals_done=2,
    complaints_open=1,
    complaints_total=3,
)


@pytest.fixture(scope="module")
def translator() -> Translator:
    return Translator.load()


def opened(
    entity_type: EntityType,
    *,
    queue: Queue = Queue.PREMOD,
    trigger: CaseTrigger = CaseTrigger.NEW_CONTENT,
    signals: tuple[str, ...] = (),
    opened_at: datetime = NOW,
    **details: object,
) -> Case:
    return Case.open(
        queue=queue,
        entity_type=entity_type,
        entity_id=new_id(),
        subject_id=UserId(new_id()),
        trigger=trigger,
        now=opened_at,
        details={"signals": list(signals), **details},
        media_ids=[MediaId(new_id())] if entity_type is EntityType.MEDIA else (),
    )


def fields(**texts: str) -> tuple[ContentField, ...]:
    return tuple(ContentField(name=name, text=text) for name, text in texts.items())


def render(case: Case, context: CaseContext, translator: Translator) -> str:
    return card_text(case, context, translator, now=NOW, admin_url=ADMIN)


def no_private_ids(case: Case, text: str) -> None:
    """Псевдонимных id объекта и пользователя в карточке больше нет — только номер кейса."""
    assert str(case.subject_id) not in text
    assert str(case.entity_id) not in text


def test_profile_card_tells_who_what_and_why(translator: Translator) -> None:
    case = opened(
        EntityType.PROFILE,
        signals=("always_review", "detector:contacts:flag:phone"),
        opened_at=NOW - timedelta(minutes=10),
    )
    context = CaseContext(
        subject=SPECIALIST,
        object=CaseObject(
            kind="profile",
            fields=fields(
                headline="Сантехник с опытом 10 лет",
                about="Устраняю засоры. Звоните +381 64 123 4567, приеду сегодня.",
            ),
        ),
    )

    text = render(case, context, translator)

    assert text.startswith("<b>P2 · Премодерация</b> · новый профиль на проверку")
    assert "👤 <b>Алексей М.</b> · специалист: Сантехника · Лиман" in text
    assert "в сервисе 3 дн. · доверие 0 · сделок: 0 · жалобы: 0 откр. из 0" in text
    assert "📄 <b>Профиль специалиста</b>" in text
    assert "<i>Коротко о себе:</i> Сантехник с опытом 10 лет" in text
    assert "<i>О себе:</i> Устраняю засоры. Звоните •••, приеду сегодня." in text
    assert "новый профиль — всегда человек; контакты (телефон) в «О себе»" in text
    assert "⏰ до 16:03 (через 20 мин)" in text  # P2 — 30 минут, открыт 10 минут назад
    assert f"Кейс <code>{case.id}</code>" in text
    assert "123 4567" not in text
    no_private_ids(case, text)


def test_job_report_card_with_budget_reporter_and_admin_button(translator: Translator) -> None:
    case = opened(
        EntityType.JOB,
        queue=Queue.FRAUD,
        trigger=CaseTrigger.REPORT,
        signals=("report:fraud",),
    )
    context = CaseContext(
        subject=CLIENT,
        object=CaseObject(
            kind="job",
            fields=fields(title="Покрасить стены", description="Предоплата 50% <на карту> & сразу"),
            budget=BudgetContext(kind="range", low=300_000, high=500_000, unit="work"),
        ),
        reports=(
            ReportContext(reason="fraud", reporter_role="pro", comment="Просит предоплату"),
            ReportContext(reason="spam", reporter_role=None, comment="x" * 300),
        ),
    )

    text = render(case, context, translator)

    assert text.startswith("<b>P1 · Мошенничество</b> · жалоба")
    assert "👤 <b>Ирина С.</b> · клиент · Детелинара" in text
    assert "в сервисе 5 ч · доверие 1 · сделок: 2 · жалобы: 1 откр. из 3" in text
    assert "<i>Описание:</i> Предоплата 50% &lt;на карту&gt; &amp; сразу" in text
    assert "<i>Бюджет:</i> 3 000–5 000 RSD" in text
    assert "жалоба от специалиста: мошенничество — «Просит предоплату»" in text
    # длинный текст жалобы — пользовательский контент: в карточку не идёт
    assert "жалоба: спам;" in text or text.count("жалоба: спам") == 1
    assert "x" * 50 not in text
    assert "⏰ до 17:43 (через 2 ч)" in text
    assert "Админка:" not in text  # публичный адрес — кнопкой
    [link] = [b for b in _flat(card_buttons(case, translator, ADMIN)) if isinstance(b, LinkButton)]
    assert link.text == "Открыть в админке"
    assert link.url == f"{ADMIN}/decide-case?case_id={case.id}"


def test_message_card_shows_only_the_flagged_message(translator: Translator) -> None:
    case = opened(EntityType.MESSAGE, queue=Queue.FRAUD, signals=("detector:scam:flag:prepayment",))
    context = CaseContext(
        subject=CLIENT,
        object=CaseObject(kind="message", fields=fields(message="Переведите 2000 на карту •••")),
    )

    text = render(case, context, translator)

    assert "сообщение в чате на проверку" in text
    assert "📄 <b>Сообщение в чате</b>\n<i>Сообщение:</i> Переведите 2000 на карту •••" in text
    assert "просьба о предоплате" in text


def test_review_card_has_rating_and_text(translator: Translator) -> None:
    case = opened(EntityType.REVIEW, signals=("classifier:spam_ad:0.91",))
    context = CaseContext(
        subject=CLIENT,
        object=CaseObject(kind="review", fields=fields(text="Всё сделал быстро"), rating=4),
    )

    text = render(case, context, translator)

    assert "новый отзыв на проверку" in text
    assert "<i>Оценка:</i> ★★★★☆" in text
    assert "<i>Текст:</i> Всё сделал быстро" in text
    assert "классификатор: спам / реклама (0.91)" in text


def test_photo_card_is_a_short_caption(translator: Translator) -> None:
    case = opened(
        EntityType.MEDIA,
        trigger=CaseTrigger.AUTO_FLAG,
        signals=("image:violence:0.74", "image:sexual:0.41"),
        purpose="portfolio",
        hidden=False,
    )
    context = CaseContext(subject=SPECIALIST, object=CaseObject(kind="portfolio_photo"))

    caption = card_caption(case, context, translator, now=NOW, admin_url=ADMIN)

    assert caption.startswith("<b>P2 · Премодерация</b> · фото: флаг автопроверки")
    assert "📄 <b>Фото в портфолио</b>" in caption
    assert "фото: насилие 0.74; фото: откровенное 0.41" in caption
    assert visible_length(caption) <= CAPTION_LIMIT - OUTCOME_RESERVE


def test_hidden_photo_is_not_sent_and_says_so(translator: Translator) -> None:
    case = opened(
        EntityType.MEDIA,
        queue=Queue.SAFETY,
        trigger=CaseTrigger.AUTO_FLAG,
        signals=("image:sexual:0.91",),
        purpose="avatar",
        hidden=True,
    )
    context = CaseContext(subject=SPECIALIST, object=CaseObject(kind="avatar"), photo_hidden=True)

    text = render(case, context, translator)

    assert text.startswith("<b>P0 · Безопасность</b> · фото скрыто автоматически")
    assert "🔒 Фото скрыто автоматически — смотреть в админке" in text
    assert "⏰ до 16:43 (через 1 ч)" in text


def test_unchecked_photo_card(translator: Translator) -> None:
    case = opened(
        EntityType.MEDIA, trigger=CaseTrigger.AUTO_FLAG, signals=("image:unchecked",), purpose="job"
    )
    context = CaseContext(subject=CLIENT, object=CaseObject(kind="job_photo"))

    text = render(case, context, translator)

    assert "<b>P2 · Премодерация</b> · проверка фото не состоялась" in text
    assert "📄 <b>Фото заявки</b>" in text


def test_dispute_card_has_parties_and_no_evidence(translator: Translator) -> None:
    case = Case.open(
        queue=Queue.FRAUD,
        entity_type=EntityType.DISPUTE,
        entity_id=new_id(),
        subject_id=UserId(new_id()),
        trigger=CaseTrigger.DISPUTE,
        now=NOW,
        details={"signals": ["dispute:no_show"], "title": "Починить кран", "kind": "no_show"},
        media_ids=[MediaId(new_id()), MediaId(new_id())],
        due=NOW + timedelta(hours=50),
    )
    context = CaseContext(
        subject=SPECIALIST,
        object=CaseObject(kind="dispute"),
        dispute=DisputeContext(
            kind="no_show",
            title="Починить кран",
            opened_by="Ирина С.",
            respondent=None,
            answered=False,
            photos=2,
        ),
    )

    text = render(case, context, translator)

    assert text.startswith("<b>P1 · Мошенничество</b> · спор по сделке")
    assert "Сделка «Починить кран»" in text
    assert "открыл спор: Ирина С. · вторая сторона: удалённый пользователь" in text
    assert "📎 2 фото — в админке" in text
    assert "спор: не пришёл" in text
    assert "⏰ до 07.10 17:43 (через 2 дн.)" in text
    for media_id in case.media_ids:
        assert str(media_id) not in text
    assert [b.text for b in _flat(card_buttons(case, translator))] == [
        "Выполнено",
        "Отменить с причиной",
        "Эскалировать",
    ]


def test_appeal_card_names_the_decision(translator: Translator) -> None:
    decision = CaseId(new_id())
    case = Case.open(
        queue=Queue.APPEALS,
        entity_type=EntityType.MESSAGE,
        entity_id=new_id(),
        subject_id=UserId(new_id()),
        trigger=CaseTrigger.APPEAL,
        now=NOW,
        details={
            "appeal_of": str(decision),
            "reason_code": "prepayment_scam",
            "signals": ["appeal:prepayment_scam"],
        },
        appeal_of=decision,
    )
    context = CaseContext(
        subject=CLIENT,
        object=CaseObject(kind="message", fields=fields(message="Переведите на карту •••")),
        appeal=AppealContext(reason_code="prepayment_scam", decided_at=NOW - timedelta(days=2)),
    )

    text = render(case, context, translator)

    assert text.startswith("<b>Апелляция</b> · пересмотр решения")
    assert "обжалуют решение «предоплата / мошенничество» от 03.10.2026" in text
    assert "appeal:" not in text
    assert str(decision) not in text


def test_complaint_about_a_deleted_account(translator: Translator) -> None:
    case = opened(
        EntityType.USER,
        queue=Queue.SAFETY,
        trigger=CaseTrigger.REPORT,
        signals=("report:offensive",),
    )
    context = CaseContext(
        subject=PersonContext(name=None, complaints_open=1, complaints_total=1),
        object=CaseObject(kind="user"),
        reports=(ReportContext(reason="offensive", reporter_role="client", comment=None),),
    )

    text = render(case, context, translator)

    assert "👤 удалённый пользователь\nжалобы: 1 откр. из 1" in text
    assert "📄 <b>Аккаунт</b>" in text
    assert "жалоба от клиента: оскорбления или угрозы" in text


def test_missing_object_points_to_the_admin(translator: Translator) -> None:
    case = opened(EntityType.JOB, signals=("risky_category",))
    context = CaseContext(subject=CLIENT, object=CaseObject(kind="job", missing=True))

    text = render(case, context, translator)

    assert "📄 <b>Заявка</b> — уже нет, смотреть в админке" in text
    assert "категория с повышенным риском" in text


def test_contacts_and_usernames_never_reach_the_card(translator: Translator) -> None:
    """Контакты в проверяемом тексте замаскированы во всех полях; что нашлось — словами."""
    case = opened(EntityType.RESPONSE, signals=("detector:contacts:flag:phone, username, email",))
    context = CaseContext(
        subject=SPECIALIST,
        object=CaseObject(
            kind="response",
            fields=fields(
                job="Повесить люстру",
                message="Пишите @ivan_master или ivan@mail.rs, тел. 064 123 45 67",
                availability="Завтра, звоните +381641234567",
            ),
        ),
    )

    text = render(case, context, translator)

    for leaked in ("ivan_master", "ivan@mail.rs", "123 45 67", "641234567"):
        assert leaked not in text
    assert "контакты (телефон, юзернейм, почта) в «Сообщение», «Когда сможет»" in text
    no_private_ids(case, text)


def test_long_content_is_trimmed_and_escaped(translator: Translator) -> None:
    case = opened(EntityType.PROFILE, signals=("always_review",))
    about = "<b>жирно</b> " + "очень длинный текст о себе " * 100
    context = CaseContext(
        subject=SPECIALIST,
        object=CaseObject(kind="profile", fields=fields(headline="Мастер", about=about)),
    )

    text = render(case, context, translator)

    assert "&lt;b&gt;жирно&lt;/b&gt;" in text
    assert "<b>жирно</b>" not in text
    about_line = next(line for line in text.splitlines() if line.startswith("<i>О себе:</i>"))
    assert about_line.endswith("…")
    assert len(about_line) < CONTENT_CHARS + 50
    assert visible_length(text) <= TEXT_LIMIT - OUTCOME_RESERVE


def test_caption_overflow_shrinks_content_then_reasons(translator: Translator) -> None:
    long_rules = tuple(f"rule:spam:flag:{'x' * 150}{n}" for n in range(8))
    case = opened(EntityType.PORTFOLIO, signals=long_rules)
    context = CaseContext(
        subject=SPECIALIST,
        object=CaseObject(kind="portfolio", fields=fields(caption="подпись " * 200)),
    )

    caption = card_caption(case, context, translator, now=NOW, admin_url=ADMIN)

    assert visible_length(caption) <= CAPTION_LIMIT - OUTCOME_RESERVE
    assert "Работа в портфолио" in caption
    assert f"Кейс <code>{case.id}</code>" in caption


def test_dev_admin_link_is_text_not_a_button(translator: Translator) -> None:
    """Telegram не примет кнопку со ссылкой на 127.0.0.1: в dev ссылка — строкой текста."""
    case = opened(EntityType.USER, trigger=CaseTrigger.AUTO_FLAG, signals=("demo",))
    context = CaseContext(subject=CLIENT, object=CaseObject(kind="user"))

    text = card_text(case, context, translator, now=NOW, admin_url=DEV_ADMIN)

    assert f"Админка: {DEV_ADMIN}/decide-case?case_id={case.id}" in text
    assert "демо-кейс: проверка чата модераторов" in text
    assert not [
        b for b in _flat(card_buttons(case, translator, DEV_ADMIN)) if isinstance(b, LinkButton)
    ]
    assert admin_buttons(case.id, translator, None) == ()


@pytest.mark.parametrize(
    ("url", "public"),
    [
        ("https://admin.sosedi.example/admin", True),
        ("https://abc-123.trycloudflare.com/admin", True),
        ("http://127.0.0.1:8000/admin", False),
        ("http://localhost:8000/admin", False),
        ("http://10.0.0.5/admin", False),
        ("http://192.168.1.10:8000/admin", False),
        ("ftp://admin.sosedi.example/admin", False),
        ("http://intranet/admin", False),
    ],
)
def test_public_url(url: str, public: bool) -> None:
    assert public_url(url) is public


def test_clip_cuts_at_a_word() -> None:
    assert clip("один  два\nтри", 50) == "один два три"
    assert clip("раз два три четыре", 12) == "раз два три…"
    assert len(clip("x" * 100, 10)) == 10


def _flat(lines: tuple[object, ...]) -> list[CallbackButton | LinkButton]:
    return [
        button
        for line in lines
        for button in (line if isinstance(line, tuple) else (line,))
        if isinstance(button, CallbackButton | LinkButton)
    ]
