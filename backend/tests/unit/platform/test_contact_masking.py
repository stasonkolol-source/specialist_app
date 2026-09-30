"""Детектор контактов и предоплаты (DEVELOPMENT_PLAN 2.4, ADR-0016 §3, ADR-0010).

Наборы — синтетика ассистента на ru, uk, sr (обе письменности) и en; реальные
обезличенные примеры владельца (K28) придут к калибровке 6.7.
"""

import pytest

from app.platform.text.contact_masking import (
    MASK,
    ContactKind,
    find_contacts,
    find_domains,
    find_prepayment,
    luhn_valid,
    mask_contacts,
)
from app.platform.text.normalize import skeleton

pytestmark = pytest.mark.unit

PHONE, CARD, LINK = ContactKind.PHONE, ContactKind.CARD, ContactKind.LINK
EMAIL, USERNAME = ContactKind.EMAIL, ContactKind.USERNAME


def found(text: str) -> list[tuple[ContactKind, str]]:
    return [(f.kind, text[f.start : f.end]) for f in find_contacts(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # телефоны: формат, разделители, страна
        ("Звоните +381 64 123 4567", [(PHONE, "+381 64 123 4567")]),
        ("064/123-45-67 после 18:00", [(PHONE, "064/123-45-67")]),
        ("тел (064) 123 45 67", [(PHONE, "064) 123 45 67")]),
        ("тел 064.12.34.56", [(PHONE, "064.12.34.56")]),
        ("00381641234567 — это я", [(PHONE, "00381641234567")]),
        ("381641234567", [(PHONE, "381641234567")]),
        ("+7 999 123-45-67", [(PHONE, "+7 999 123-45-67")]),
        # обфускация: цифры словами, «О» вместо нуля, по одной цифре
        (
            "ноль шесть четыре один два три четыре пять шесть семь",
            [(PHONE, "ноль шесть четыре один два три четыре пять шесть семь")],
        ),
        ("nula šest četiri 1 2 3 4 5 6 7", [(PHONE, "nula šest četiri 1 2 3 4 5 6 7")]),
        ("нула шест четири 123 45 67", [(PHONE, "нула шест четири 123 45 67")]),
        ("нуль шість сім 123 45 67", [(PHONE, "нуль шість сім 123 45 67")]),
        ("zero six four one two three 45 67", [(PHONE, "zero six four one two three 45 67")]),
        ("ноль шестьдесят четыре 123 45 67", [(PHONE, "ноль шестьдесят четыре 123 45 67")]),
        ("O64 1234567", [(PHONE, "O64 1234567")]),
        ("Pozovite 0 6 4 1 2 3 4 5 6 7", [(PHONE, "0 6 4 1 2 3 4 5 6 7")]),
        # карты: по контрольной сумме Луна
        ("карта 4111 1111 1111 1111", [(CARD, "4111 1111 1111 1111")]),
        ("kartica 5555-5555-5555-4444", [(CARD, "5555-5555-5555-4444")]),
        # ссылки и мессенджеры
        ("сайт majstor.rs", [(LINK, "majstor.rs")]),
        ("https://example.com/x?y=1 смотри", [(LINK, "https://example.com/x?y=1")]),
        ("пишите в t . me / ivan_master", [(LINK, "t . me / ivan_master")]),
        ("wa.me/381641234567", [(LINK, "wa.me/381641234567")]),
        ("mojsajt [.] rs", [(LINK, "mojsajt [.] rs")]),
        ("www.majstor-beograd.com", [(LINK, "www.majstor-beograd.com")]),
        # e-mail и @username
        ("ivan.petrov@gmail.com", [(EMAIL, "ivan.petrov@gmail.com")]),
        ("mail: ivan (at) gmail dot com", [(EMAIL, "ivan (at) gmail dot com")]),
        ("ivan собака mail точка ru", [(EMAIL, "ivan собака mail точка ru")]),
        ("мой телеграм @ivan_master", [(USERNAME, "@ivan_master")]),
    ],
)
def test_contacts_are_found(text: str, expected: list[tuple[ContactKind, str]]) -> None:
    assert found(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Срок 01.10.2026 - 05.10.2026, цена 1 000 000 RSD",
        "c 1.10. по 5.10., с 9:00 до 18:00",
        "01-10-2026 и 12/10/26",
        "Размер 2x3 м, 120 м², 3 комнаты, этаж 5/9",
        "Цена 25.000 dinara, avans nije potreban",
        "Позвоните через приложение, номер после договорённости",
        "Call me. Me too",
        "т.е. и т.д., ул. Бульвар 12",
        "Бюджет 60 000 000 динаров",
        "шестьдесят четыре",
        "Заказ №1234567 от 2026 года",
        "email me later, at home",
        "@ab — слишком коротко для Telegram",
        "4111 1111 1111 1112",  # контрольная сумма не сходится
    ],
)
def test_ordinary_text_is_left_alone(text: str) -> None:
    assert found(text) == []


def test_masking_keeps_the_rest_of_the_text() -> None:
    text = "Иван, 064 123 45 67 или @ivan_master, сайт majstor.rs. Приеду завтра."

    assert mask_contacts(text) == f"Иван, {MASK} или {MASK}, сайт {MASK}. Приеду завтра."


def test_email_is_one_finding_not_an_email_and_a_username() -> None:
    assert found("ivan@gmail.com") == [(EMAIL, "ivan@gmail.com")]


@pytest.mark.parametrize(
    "text",
    [
        "Нужна предоплата 50%",
        "pred0plata обязательна",
        "п.р.е.д.о.п.л.а.т.а",
        "ПРЕДОПЛАААТА",
        "передоплата 30%",
        "avans 30%",
        "аванс унапред",
        "plaćanje unapred",
        "уплата унапред на рачун",
        "капара 5000",
        "переведите на карту",
        "скиньте на карту сначала",
        "pay upfront please",
        "advance payment required",
    ],
)
def test_prepayment_requests_are_recognised(text: str) -> None:
    assert find_prepayment(text)


@pytest.mark.parametrize(
    "text",
    [
        "Оплата после работы",
        "Плаћање после посла",
        "Platim kad završite",
        "Pay after the job is done",
        "Предлагаю план работ",
    ],
)
def test_payment_after_the_job_is_not_prepayment(text: str) -> None:
    assert not find_prepayment(text)


def test_skeleton_folds_scripts_and_disguises() -> None:
    assert skeleton("Предоплата") == skeleton("predoplata") == skeleton("пред0плата")
    assert skeleton("п.р.е.д.о.п.л.а.т.а") == "predoplata"
    assert skeleton("ПРЕДОПЛАААТА") == "predoplata"
    assert skeleton("Plaćanje") == skeleton("Плаћање") == "placanje"
    assert skeleton("2026 год") == "2026 god"  # число без букв остаётся числом
    assert skeleton("massage") == skeleton("masssage") == skeleton("MASSAGE") == "masage"
    assert skeleton("Заранее 1000") == "zarane 1000"  # двойные буквы — одна, цифры — как есть
    assert skeleton("3вони") == skeleton("звони") == "zvoni"  # в кириллице 3 — это з
    assert skeleton("4ел") == skeleton("чел") == "cel"
    assert skeleton("k@zino ca$ino") == "kazino casino"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Pogledaj https://Bit.ly/3xYz i www.example.rs/katalog", ("bit.ly", "example.rs")),
        ("пиши: t . me/sosed_help или wa.me/381641234567", ("t.me", "wa.me")),
        ("scam-shop [.] com/pay", ("scam-shop.com",)),
        ("почта ivan (at) mail точка ru", ("mail.ru",)),
        ("viber://chat?number=381641234567 и @ivan_petrov", ()),
        ("Цена 1.500 дин, срок 12.10.2026", ()),
    ],
)
def test_domains_of_links_and_emails(text: str, expected: tuple[str, ...]) -> None:
    assert find_domains(text) == expected


def test_luhn() -> None:
    assert luhn_valid("4111111111111111")
    assert not luhn_valid("4111111111111112")
