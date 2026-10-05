"""Карточка «Поделиться» (DEVELOPMENT_PLAN 7.4): что видно в чате и в подписи к ссылке.

У специалиста — то, что публично на S08: «коротко о себе», рейтинг или «Новый специалист»,
«Телефон подтверждён», район и цена «от»; у заявки — бюджет и время словами карточки B1 и место.
Подпись к ссылке — первые две строки карточки простым текстом. Каталоги — настоящие
(backend/locales).
"""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.interfaces.http.views.share import job_card, specialist_card
from app.modules.jobs.api import PublicJob
from app.modules.reviews.api import RatingSummary
from app.platform.i18n.translator import Translator
from app.platform.kernel.ids import CityId, UserId, new_id
from app.platform.kernel.localized import Locale

pytestmark = pytest.mark.unit

SCRIPTS = (Locale.RU, Locale.SR_CYRL, Locale.SR_LATN)
# 17:32 по Белграду 3 октября 2026 (UTC+2)
NOW = datetime(2026, 10, 3, 15, 32, tzinfo=UTC)
NAME = "Алексей Морозов"
HEADLINE = "Электрик · мелкий ремонт · люстры"
PLACE = "Лиман, Нови-Сад"
JOB = PublicJob(
    client_id=UserId(new_id()),
    title="Повесить люстру",
    city_id=CityId(1),
    district_id=None,
    budget_type="fixed",
    budget_min=500_000,
    budget_max=None,
    budget_unit="work",
    urgency="today",
    preferred_from=datetime(2026, 10, 3, 16, 0, tzinfo=UTC),
    preferred_to=datetime(2026, 10, 3, 19, 0, tzinfo=UTC),
)


@pytest.fixture(scope="module")
def translator() -> Translator:
    return Translator.load()


def rated(count: int, average: float = 4.87) -> RatingSummary:
    """Четвёрки и пятёрки так, чтобы простое среднее звёзд было около `average`: показывают его,
    а не байесовское (UXM-17)."""
    fives = round((average - 4) * count)
    return RatingSummary(count=count, average=average, distribution=(0, 0, 0, count - fives, fives))


def test_specialist_card_shows_what_s08_shows(translator: Translator) -> None:
    card, caption = specialist_card(
        translator,
        Locale.RU,
        name=NAME,
        headline=HEADLINE,
        rating=rated(37),
        phone_verified=True,
        place=PLACE,
        price_from=200_000,
    )

    assert card.text == (
        "<b>Алексей Морозов</b> — специалист в «Соседях»\n"
        "Электрик · мелкий ремонт · люстры\n"
        "★ 4,9 — 37 отзывов\n"
        "Телефон подтверждён\n"
        "Лиман, Нови-Сад · от 2\u00a0000 RSD"
    )
    assert caption == "Алексей Морозов — специалист в «Соседях»\nЭлектрик · мелкий ремонт · люстры"
    assert (card.title, card.description, card.button_text) == (NAME, HEADLINE, "Открыть профиль")


def test_new_specialist_without_phone_price_or_headline(translator: Translator) -> None:
    """Отзывов меньше трёх — «Новый специалист», как на S08; неподтверждённый телефон и цену не
    называем вовсе; без «коротко о себе» подпись берёт следующую строку."""
    for rating in (None, rated(2)):
        card, caption = specialist_card(
            translator,
            Locale.RU,
            name=NAME,
            headline=None,
            rating=rating,
            phone_verified=False,
            place=PLACE,
            price_from=None,
        )

        assert card.text == (
            "<b>Алексей Морозов</b> — специалист в «Соседях»\nНовый специалист\nЛиман, Нови-Сад"
        )
        assert caption == "Алексей Морозов — специалист в «Соседях»\nНовый специалист"


@pytest.mark.parametrize(
    ("locale", "count", "average", "line"),
    [
        (Locale.RU, 21, 4.66, "★ 4,7 — 21 отзыв"),
        (Locale.RU, 22, 5.0, "★ 5,0 — 22 отзыва"),
        (Locale.RU, 111, 4.9, "★ 4,9 — 111 отзывов"),
        (Locale.RU, 1234, 4.9, "★ 4,9 — 1\u00a0234 отзыва"),
        (Locale.SR_LATN, 21, 4.9, "★ 4,9 — 21 utisak"),
        (Locale.SR_LATN, 3, 4.67, "★ 4,7 — 3 utiska"),  # у трёх оценок 4,9 не бывает
        (Locale.SR_LATN, 11, 4.9, "★ 4,9 — 11 utisaka"),
        (Locale.SR_CYRL, 5, 4.8, "★ 4,8 — 5 утисака"),
    ],
)
def test_rating_line_agrees_with_the_count(
    translator: Translator, locale: Locale, count: int, average: float, line: str
) -> None:
    card, _ = specialist_card(
        translator,
        locale,
        name=NAME,
        headline=None,
        rating=rated(count, average),
        phone_verified=False,
        place=None,
        price_from=None,
    )

    assert card.text.splitlines()[1] == line


def test_long_headline_and_name_stay_one_line_of_text(translator: Translator) -> None:
    """«Коротко о себе» до 80 знаков с переносом строки и разметкой: в карточке — одной строкой и
    текстом, подпись к ссылке — всё так же две строки."""
    headline = "Ремонт <b>под ключ</b> &\nсантехника, электрика, " + "плитка " * 5
    card, caption = specialist_card(
        translator,
        Locale.RU,
        name="Ana & <Co>",
        headline=headline.strip(),
        rating=None,
        phone_verified=False,
        place=None,
        price_from=None,
    )

    flat = " ".join(headline.split())
    assert card.text.splitlines() == [
        "<b>Ana &amp; &lt;Co&gt;</b> — специалист в «Соседях»",
        flat.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"),
        "Новый специалист",
    ]
    assert caption == f"Ana & <Co> — специалист в «Соседях»\n{flat}"


def test_job_card_uses_the_b1_budget_and_time(translator: Translator) -> None:
    card, caption = job_card(translator, Locale.RU, JOB, PLACE, NOW)

    assert card.text == (
        "<b>Повесить люстру</b> — заявка в «Соседях»\n"
        "5\u00a0000 RSD · сегодня 18:00–21:00\n"
        "Лиман, Нови-Сад"
    )
    assert caption == "Повесить люстру — заявка в «Соседях»\n5\u00a0000 RSD · сегодня 18:00–21:00"
    assert (card.title, card.description, card.button_text) == (
        "Повесить люстру",
        PLACE,
        "Открыть заявку",
    )


def test_job_card_variants(translator: Translator) -> None:
    """Диапазон с единицей и завтра; договорная по срочности и без места; без времени и
    срочности — один бюджет."""
    tomorrow = replace(
        JOB,
        budget_type="range",
        budget_min=300_000,
        budget_max=500_000,
        budget_unit="hour",
        preferred_from=datetime(2026, 10, 4, 8, 0, tzinfo=UTC),
        preferred_to=None,
    )
    negotiable = replace(
        JOB,
        budget_type="negotiable",
        budget_min=None,
        urgency="flexible",
        preferred_from=None,
        preferred_to=None,
    )
    unknown = replace(JOB, urgency="", preferred_from=None, preferred_to=None)

    assert job_card(translator, Locale.RU, tomorrow, PLACE, NOW)[0].text.splitlines()[1] == (
        "3\u00a0000–5\u00a0000 RSD в час · завтра 10:00"
    )
    assert job_card(translator, Locale.RU, negotiable, None, NOW)[0].text.splitlines()[1:] == [
        "Договорная · когда удобно"
    ]
    assert job_card(translator, Locale.RU, unknown, PLACE, NOW)[1].splitlines()[1] == (
        "5\u00a0000 RSD"
    )


@pytest.mark.parametrize("locale", SCRIPTS)
def test_cards_on_three_scripts(translator: Translator, locale: Locale) -> None:
    specialist, _ = specialist_card(
        translator,
        locale,
        name="Marko",
        headline=HEADLINE,
        rating=rated(37),
        phone_verified=True,
        place=PLACE,
        price_from=200_000,
    )
    job, _ = job_card(translator, locale, JOB, PLACE, NOW)

    for card in (specialist, job):
        assert "share." not in card.text + card.button_text
        assert "notifications." not in card.text
    if locale is Locale.SR_LATN:
        assert specialist.text.splitlines()[0] == "<b>Marko</b> — stručnjak u aplikaciji „Sosedi“"
        assert specialist.text.splitlines()[2:4] == ["★ 4,9 — 37 utisaka", "Telefon potvrđen"]
        assert job.text.splitlines()[1] == "5.000 RSD · danas 18:00–21:00"
