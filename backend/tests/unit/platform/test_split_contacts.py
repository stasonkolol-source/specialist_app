"""Контакт по частям в нескольких сообщениях одного отправителя (QA ADV-06): окно детектора
`find_split_contacts` — что скрыть в каждом сообщении, и что обычные числа не склеиваются."""

import pytest

from app.platform.text.contact_masking import (
    MASK,
    ContactKind,
    Finding,
    find_split_contacts,
    mask_findings,
)


def masked(parts: list[str]) -> list[str]:
    found = find_split_contacts(parts)
    return [mask_findings(part, spans) for part, spans in zip(parts, found, strict=True)]


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        # номер из двух и трёх сообщений; слова вокруг частей номер не рвут (как в отчёте QA)
        (["064", "123 45 67"], [MASK, MASK]),
        (
            ["мой номер начинается 064", "потом 123", "и в конце 45 67"],
            [f"мой номер начинается {MASK}", f"потом {MASK}", f"и в конце {MASK}"],
        ),
        (["+381", "64 123 4567"], [MASK, MASK]),
        (["Звоните 06", "4 123 45 67, жду"], [f"Звоните {MASK}", f"{MASK}, жду"]),
        # ник и почта: вплотную и после названия мессенджера
        (["мой ник @qa", "_contact_test"], [f"мой ник {MASK}", MASK]),
        (["@qa_", "contact", "_test"], [MASK, MASK, MASK]),
        (["Мой телеграм:", "qa_contact_test"], ["Мой телеграм:", MASK]),
        (["ivan.petrov", "@gmail.com"], [MASK, MASK]),
    ],
)
def test_contact_split_across_messages_is_masked_in_every_part(
    parts: list[str], expected: list[str]
) -> None:
    assert masked(parts) == expected


@pytest.mark.parametrize(
    "parts",
    [
        # цены, даты и время, адрес — обычные числа в переписке
        ["Цена 3000", "или 2500 со скидкой", "материалы 1500"],
        ["Могу 06.10", "или 07.10 в 18:00"],
        ["Улица Футошка 12", "квартира 5", "подъезд 2"],
        ["Буду в 15", "дом 064"],
        # числа одного сообщения, разделённые словами, не склеиваются — как в одиночном
        ["дом 064, квартира 123", "4567"],
        # конец предложения и слово с заглавной — не ссылка
        ["Хорошо.", "Rs?"],
        # номер целиком в одном сообщении — скрывает mask_contacts, окну скрывать нечего
        ["064 123 45 67", "спасибо"],
        # до нового сообщения контакт не доходит — его проверили, когда пришла вторая часть
        ["064", "123 45 67", "Спасибо"],
        ["064"],
    ],
)
def test_ordinary_numbers_and_whole_contacts_are_not_split_contacts(parts: list[str]) -> None:
    assert find_split_contacts(parts) == [[] for _ in parts]


def test_overlapping_findings_get_one_mask() -> None:
    found = [Finding(ContactKind.PHONE, 4, 9), Finding(ContactKind.PHONE, 6, 11)]

    assert mask_findings("tel 064 123 45", found) == f"tel {MASK} 45"
    assert mask_findings("без контактов", []) == "без контактов"
