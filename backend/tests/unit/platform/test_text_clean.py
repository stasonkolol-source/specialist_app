"""Текст с клиента (QA ADV-03, ADV-04): NUL и невидимые символы не доходят до базы и не
проходят проверку «не пусто»; эмодзи, пробелы и переводы строк целы — пробелы по краям
обрезает и пустой текст отклоняет домен своим кодом, как раньше."""

import pytest
from pydantic import BaseModel, ValidationError

from app.modules.deals.http.schemas import DisputeAnswerIn, DisputeIn
from app.modules.identity.http.schemas import MeUpdateIn
from app.modules.jobs.http.schemas import JobIn, ResponseTemplateIn
from app.modules.messaging.http.schemas import MessageIn
from app.modules.reviews.http.schemas import ReplyIn
from app.platform.text.clean import clean_text

pytestmark = pytest.mark.unit

ZWSP, ZWNJ, ZWJ, WJ, BOM = "\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"
INVISIBLE = [
    ZWSP + WJ + BOM + ZWSP + WJ + BOM,  # заголовок заявки из находки ADV-04
    ZWSP + ZWNJ + ZWJ + BOM,  # сообщение чата
    ZWSP + ZWNJ + ZWJ + WJ + BOM,  # имя: WJ и BOM раньше оставались
    "\u3164" * 5,  # заполнитель хангыля — «невидимое имя»
    "\ufe0f" * 5,  # селекторы варианта без символа
    " \u00a0\u2800\u202e\u00ad ",  # пробелы, пробел Брайля, bidi-override, мягкий перенос
]


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("[QA] a\u0000b", "[QA] ab"),
        ("a\u0001b\u007fc\u0085d\u009fe", "abcde"),
        (f"a{ZWSP}b{WJ}c{BOM}d\u00ade", "abcde"),
        ("bidi \u202eтекст\u202c", "bidi текст"),
        ("  строка 1\r\nстрока 2\rстрока 3\n\n", "  строка 1\nстрока 2\nстрока 3\n\n"),
        ("\tколонка\tколонка\t", "\tколонка\tколонка\t"),
        (f"{ZWJ}a{ZWJ}{ZWJ}{ZWJ}b{ZWJ}", f"a{ZWJ}b"),
    ],
)
def test_controls_and_format_characters_are_removed(raw: str, clean: str) -> None:
    assert clean_text(raw) == clean


@pytest.mark.parametrize(
    "emoji",
    [
        f"\U0001f469{ZWJ}\U0001f527",  # женщина-механик: ZWJ
        f"\U0001f468{ZWJ}\U0001f469{ZWJ}\U0001f467",  # семья
        "❤\ufe0f",  # красное сердце: селектор варианта
        "\U0001f3f4\U000e0067\U000e0062\U000e0073\U000e0063\U000e0074\U000e007f",  # флаг
        "\U0001f44d\U0001f3fd",  # оттенок кожи
    ],
)
def test_emoji_sequences_survive(emoji: str) -> None:
    assert clean_text(f"Спасибо {emoji}") == f"Спасибо {emoji}"
    assert clean_text(emoji) == emoji


@pytest.mark.parametrize("raw", INVISIBLE)
def test_invisible_only_text_becomes_blank(raw: str) -> None:
    assert clean_text(raw).strip() == ""


@pytest.mark.parametrize("raw", [raw for raw in INVISIBLE if not raw.isspace() and " " not in raw])
def test_invisible_text_is_rejected_where_text_is_required(raw: str) -> None:
    """Пустое после очистки — 422 до домена: заголовок заявки, сообщение, ответ на отзыв,
    шаблон, имя (ADV-04)."""
    job = {
        "category_id": 1,
        "urgency": "this_week",
        "budget_type": "negotiable",
        "city_id": 1,
    }
    with pytest.raises(ValidationError):
        JobIn.model_validate({**job, "title": raw})
    with pytest.raises(ValidationError):
        JobIn.model_validate({**job, "title": f"ab{raw}c"})  # минимум — по видимым
    with pytest.raises(ValidationError):
        MessageIn.model_validate({"body": raw})
    with pytest.raises(ValidationError):
        ReplyIn.model_validate({"body": raw})
    with pytest.raises(ValidationError):
        ResponseTemplateIn.model_validate(
            {"title": raw, "message": "Могу сегодня", "price_type": "negotiable"}
        )
    with pytest.raises(ValidationError):
        MeUpdateIn.model_validate({"display_name": raw})
    # описание спора проверяет домен: после очистки оно пустое, как и пустая строка
    assert DisputeIn.model_validate({"kind": "other", "description": raw}).description == ""


def test_nul_is_stripped_from_every_text_the_finding_listed() -> None:
    """ADV-03: отклик, шаблон, чат, ответ на отзыв, спор — NUL вычищен, остальное цело."""
    nul = "[QA] a\u0000b"
    template = ResponseTemplateIn.model_validate(
        {"title": nul, "message": nul, "availability_note": nul, "price_type": "negotiable"}
    )
    assert (template.title, template.message, template.availability_note) == ("[QA] ab",) * 3
    message = MessageIn.model_validate({"body": nul, "client_msg_id": nul})
    assert (message.body, message.client_msg_id) == ("[QA] ab", "[QA] ab")
    assert ReplyIn.model_validate({"body": nul}).body == "[QA] ab"
    assert DisputeIn.model_validate({"kind": "other", "description": nul}).description == "[QA] ab"
    assert DisputeAnswerIn.model_validate({"text": nul}).text == "[QA] ab"


@pytest.mark.parametrize(
    ("model", "body", "code"),
    [
        (MeUpdateIn, {"display_name": ""}, "string_too_short"),
        (MeUpdateIn, {"display_name": "x" * 65}, "string_too_long"),
        (MessageIn, {"body": ""}, "string_too_short"),
        (ReplyIn, {"body": "x" * 2001}, "string_too_long"),
    ],
)
def test_length_errors_keep_their_codes(
    model: type[BaseModel], body: dict[str, str], code: str
) -> None:
    """Очистка не меняет коды ошибок длины: клиент и тексты ошибок их знают."""
    with pytest.raises(ValidationError) as error:
        model.model_validate(body)
    assert error.value.errors()[0]["type"] == code


def test_job_languages_are_the_supported_codes() -> None:
    """ADV-05: только ru, sr, en, uk — мусор и код в 5000 символов — 422."""
    job = {
        "title": "Починить розетку",
        "category_id": 1,
        "urgency": "this_week",
        "budget_type": "negotiable",
        "city_id": 1,
    }
    assert JobIn.model_validate({**job, "languages": ["ru", "sr"]}).languages == ["ru", "sr"]
    for junk in (["xx-evil"], ["<script>", "ru"], ["a" * 5000]):
        with pytest.raises(ValidationError):
            JobIn.model_validate({**job, "languages": junk})
