"""Детектор контактов и предоплаты (DEVELOPMENT_PLAN 2.4, ADR-0016 §3, ADR-0010).

Наборы — синтетика ассистента на ru, uk, sr (обе письменности) и en; реальные
обезличенные примеры владельца (K28) придут к калибровке 6.7.
"""

import time

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
ACCOUNT = ContactKind.ACCOUNT
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
        # номер среди других чисел и в чужих форматах
        ("Stan 45, 064 123 4567", [(PHONE, "064 123 4567")]),
        ("Cena 3000 064 123 4567", [(PHONE, "064 123 4567")]),
        ("Soba 3 - 064 123 4567", [(PHONE, "064 123 4567")]),
        ("7 064 123 4567", [(PHONE, "064 123 4567")]),
        ("064 123 4567 12", [(PHONE, "064 123 4567")]),
        ("Звоните 8 999 123-45-67", [(PHONE, "8 999 123-45-67")]),
        ("8(916)123-45-67", [(PHONE, "8(916)123-45-67")]),
        ("7 999 123 45 67", [(PHONE, "7 999 123 45 67")]),
        ("380 67 123 4567", [(PHONE, "380 67 123 4567")]),
        ("064*123*4567 или 064|123|4567", [(PHONE, "064*123*4567"), (PHONE, "064|123|4567")]),
        # цифры, которые выглядят иначе: полноширинные, «математические», с невидимым символом
        ("０６４１２３４５６７", [(PHONE, "０６４１２３４５６７")]),
        ("𝟎𝟔𝟒𝟏𝟐𝟑𝟒𝟓𝟔𝟕", [(PHONE, "𝟎𝟔𝟒𝟏𝟐𝟑𝟒𝟓𝟔𝟕")]),
        ("064\u200b123\u200b4567", [(PHONE, "064\u200b123\u200b4567")]),
        (
            "nula šest četiri, jedan dva tri, 4567",
            [(PHONE, "nula šest četiri, jedan dva tri, 4567")],
        ),
        # ссылки и почта со спрятанными точками и зоной прописными
        ("bit[dot]ly/abc", [(LINK, "bit[dot]ly/abc")]),
        ("MAJSTOR.RS", [(LINK, "MAJSTOR.RS")]),
        ("a.b.majstor.co.rs", [(LINK, "a.b.majstor.co.rs")]),
        ("ivan@mail.yandex.ru", [(EMAIL, "ivan@mail.yandex.ru")]),
        ("majstor.me/profil", [(LINK, "majstor.me/profil")]),
        # время рядом с номером не прячет его: гасится только диапазон и «с 9:00»
        ("Pozovi 064 1:23 4567", [(PHONE, "064 1:23 4567")]),
        ("Broj: 064 123 12:34", [(PHONE, "064 123 12:34")]),
        ("Тел 8 999 12:34 567", [(PHONE, "8 999 12:34 567")]),
        # невидимый символ внутри адреса, разложенная диакритика, мессенджер с «@ »
        ("tiny\u200burl.com/abc", [(LINK, "tiny\u200burl.com/abc")]),
        ("iv\u200ban.petrov@gmail.com", [(EMAIL, "iv\u200ban.petrov@gmail.com")]),
        (
            "nula s\u030cest c\u030cetiri 123 4567",
            [(PHONE, "nula s\u030cest c\u030cetiri 123 4567")],
        ),
        ("tg @ ivan_master", [(USERNAME, "@ ivan_master")]),
        ("telegram: @ ivan_master", [(USERNAME, "@ ivan_master")]),
        # счёт сербского банка (контрольное число по модулю 97)
        ("Uplata na 160-0000000123456-54", [(ACCOUNT, "160-0000000123456-54")]),
        ("RS35 265-1000000000123-70", [(ACCOUNT, "RS35 265-1000000000123-70")]),  # IBAN целиком
        # IBAN целиком (контрольные цифры по модулю 97), ник мессенджера без «@», почта без зоны
        ("IBAN: RS35 1600 0000 0012 3456 54", [(ACCOUNT, "RS35 1600 0000 0012 3456 54")]),
        ("IBAN: DE89 3704 0044 0532 0130 00", [(ACCOUNT, "DE89 3704 0044 0532 0130 00")]),
        ("tg: ivan_master", [(USERNAME, "ivan_master")]),
        ("telegram ivan_master99", [(USERNAME, "ivan_master99")]),
        ("в телеграм — ivan_master", [(USERNAME, "ivan_master")]),
        ("пишите на ivan.petrov@gmail", [(EMAIL, "ivan.petrov@gmail")]),
        # номер вплотную к буквам и к знакам «№», «℡» (NFKC делает из них буквы)
        ("Zovi 064 123 4567a", [(PHONE, "064 123 4567")]),
        ("Tel064 123 4567", [(PHONE, "064 123 4567")]),
        ("Zovi064/123-4567", [(PHONE, "064/123-4567")]),
        ("0641234567ivan", [(PHONE, "0641234567")]),
        ("тел0641234567", [(PHONE, "0641234567")]),
        ("Мой №064 123 45 67", [(PHONE, "064 123 45 67")]),
        ("Viber℡064 123 4567", [(PHONE, "064 123 4567")]),
        # диакритика в адресе, нике и зоне
        ("t.mé/ivan_master", [(LINK, "t.mé/ivan_master")]),
        ("ivan@gmail.cóm", [(EMAIL, "ivan@gmail.cóm")]),
        ("@ivän_master", [(USERNAME, "@ivän_master")]),
        ("majstor.ŕs", [(LINK, "majstor.ŕs")]),
        # к карте приклеились срок и CVV
        ("Kartica 4111 1111 1111 1111 12/28", [(CARD, "4111 1111 1111 1111")]),
        ("Card 4111 1111 1111 1111 123", [(CARD, "4111 1111 1111 1111")]),
        ("4111111111111111 12/28", [(CARD, "4111111111111111")]),
        # разделители: юникодные дефисы и минус, буллет, тильда, заполнители хангыля и Брайля
        ("064\u2011123\u20114567", [(PHONE, "064\u2011123\u20114567")]),
        ("064\u2010123\u20104567", [(PHONE, "064\u2010123\u20104567")]),
        ("064\u2212123\u22124567", [(PHONE, "064\u2212123\u22124567")]),
        ("4111\u20111111\u20111111\u20111111", [(CARD, "4111\u20111111\u20111111\u20111111")]),
        ("064•123•4567", [(PHONE, "064•123•4567")]),
        ("064~123~4567", [(PHONE, "064~123~4567")]),
        ("064\u3164123\u31644567", [(PHONE, "064\u3164123\u31644567")]),
        ("064\u2800123\u28004567", [(PHONE, "064\u2800123\u28004567")]),
        # пересекающиеся находки — одна: номер внутри ссылки
        ("majstor.rs/064 123 4567", [(LINK, "majstor.rs/064 123 4567")]),
        # ник с точкой, точка в скобках внутри почты
        ("@ivan.master", [(USERNAME, "@ivan.master")]),
        ("insta: @ ivan.master", [(USERNAME, "@ ivan.master")]),
        ("ivan[.]petrov@gmail.com", [(EMAIL, "ivan[.]petrov@gmail.com")]),
        # ноль отдельно, счёт без нулей в середине, IBAN без пробелов
        ("0 64 123 45 67", [(PHONE, "0 64 123 45 67")]),
        ("Račun 160-123456-54", [(ACCOUNT, "160-123456-54")]),
        ("RS35265100000000012370", [(ACCOUNT, "RS35265100000000012370")]),
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
        # время и диапазоны
        "Dostupan sam 08.00-16.00",
        "termin od 07.30 - 09.00",
        "с 08.00–17.00",
        "od 01.10-05.10",
        # точка без пробела — конец предложения, а не домен или почта
        "Uradio sam posao.To je sve",
        "televizor.TV",
        "Есть собака лабрадор.Нужен выгул",
        "My dog is at home.Please come",
        # цены через запятую — не карта; «@» вместо «в» — не @username
        "Cene: 1000, 1200, 1800, 2000 din",
        "I'm @ home all day",
        "Available @ weekends",
        "1111 2222 3333 4444",  # 1 — не платёжная система
        # размеры, часы работы, прайс через пробел
        "Dimenzije 0 60 120 180 240",
        "Radno vreme 0800-1600",
        "Termini 08 09 10 11 h",
        "Cene 2000 2500 3000 3500 din",
        "160-0000000123456-78",  # контрольное число не сходится — не счёт
        # зона-слово без пути — конец предложения
        "uradio sam posao.to je sve",
        "zavrsio sam.si li tu",
        "stigao sam.de si",
        # мессенджер без ника, почта как слово, IBAN с неверной контрольной суммой
        "у меня telegram premium",
        "zovi me na viber",
        "Dostava na mail adresu",
        "IBAN: RS35 1600 0000 0012 3456 78",
        # списки времени
        "Termini 09:00 10:30 12:00",
        "Свободные окна: 09:00 10:00 11:00 12:00",
        "Slobodni termini: 09.30 10.30 11.30 12.30",
        "Свободно 08:00 / 09:30 / 11:00",
    ],
)
def test_ordinary_text_is_left_alone(text: str) -> None:
    assert found(text) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # QA ADV-06: кириллица-двойник в ссылке, нике и почте (т, м, е, а, о, с — кириллические)
        ("[QA] т.ме/qa_contact_test", [(LINK, "т.ме/qa_contact_test")]),
        ("т.ме / qa_contact", [(LINK, "т.ме / qa_contact")]),
        ("Т.МЕ/IVAN_MASTER", [(LINK, "Т.МЕ/IVAN_MASTER")]),
        ("t.mе/ivan_master", [(LINK, "t.mе/ivan_master")]),
        ("пишите @qа_cоntact", [(USERNAME, "@qа_cоntact")]),
        ("почта ivan@gmail.соm", [(EMAIL, "ivan@gmail.соm")]),
        # ник по буквам через пробелы и знаки
        ("[QA] телеграм: q a _ c o n t a c t", [(USERNAME, "q a _ c o n t a c t")]),
        ("tg @ i v a n _ m a s t e r", [(USERNAME, "i v a n _ m a s t e r")]),
        ("@ q a _ c o n t a c t", [(USERNAME, "q a _ c o n t a c t")]),
        ("инста: i-v-a-n-m-a-s-t-e-r", [(USERNAME, "i-v-a-n-m-a-s-t-e-r")]),
        ("t.me/q a _ c o n t a c t", [(LINK, "t.me/q a _ c o n t a c t")]),
    ],
)
def test_lookalikes_and_spaced_handles_are_found(
    text: str, expected: list[tuple[ContactKind, str]]
) -> None:
    assert found(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "Wi-Fi-роутер и SMS-ку настрою",
        "iPhone-а и MacBook-и чиню",
        "т.е. и т.д., ул. Бульвар 12",
        "Telegram: напишу позже",
        "a b c — варианты ответа",
    ],
)
def test_mixed_script_words_are_not_contacts(text: str) -> None:
    assert found(text) == []


@pytest.mark.parametrize(
    "text",
    ["Tel: ¹²³⁴⁵⁶⁷⁸⁹¹²³⁴", "①②③④⑤⑥⑦⑧⑨①②③④", "⑴⑵⑶⑷⑸⑹⑺⑻⑼⑽⑾⑿⒀", "٠٦٤١٢٣٤٥٦٧٨٩٠١٢"],
)
def test_unusual_digits_never_crash(text: str) -> None:
    mask_contacts(text)
    find_domains(text)
    assert luhn_valid("٤١١١") is False  # только цифры ASCII


@pytest.mark.parametrize(
    "text",
    [
        "a-" * 10_000,
        "dobar-dan-" * 2_000,
        "1.2.3.4.5.6.7.8.9." * 1_100,
        "x[.]" * 5_000,
        "x dot " * 3_400,
        "a@b." * 5_000,
        "ivan собака x точка " * 1_000,
        "t" + " " * 20_000 + "x",
        "1 " * 10_000,
        "avans " * 3_300,
        "bez avansa ne avansa " * 4_000,  # одна фраза из тысяч повторов ключа
        "a " * 10_000 + "bc",
        # длинные пробелы вокруг «@», «at», точки: каждое совпадение не перебирает их заново
        "a" + " " * 19_993 + "@b.com",
        "a@" + " " * 19_990 + "b.com",
        "a" + " " * 19_990 + " at b.com",
        "t" + " " * 19_990 + ". me/x",
        "x [.] " * 3_000,
        "a " + "(.) " * 5_000,
    ],
    ids=lambda text: text[:12],
)
def test_adversarial_input_is_linear(text: str) -> None:
    started = time.perf_counter()
    mask_contacts(text)
    find_domains(text)
    find_prepayment(text)
    skeleton(text)
    assert time.perf_counter() - started < 3.0  # линейно — десятые доли; квадратично — 5–35 с


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


@pytest.mark.parametrize(
    ("text", "asks"),
    [
        # честные: «без предоплаты» — самый частый оборот
        ("Работаю без предоплаты, оплата по факту", False),
        ("Radim bez avansa", False),
        ("avans nije potreban", False),
        ("No upfront payment", False),
        ("Предоплата не нужна", False),
        ("Не беру аванс", False),
        ("Uplata unapred nije potrebna", False),
        ("I don't take any deposit", False),
        # двойное отрицание — требование
        ("Bez avansa ne dolazim", True),
        ("Без предоплаты не выезжаю", True),
        # «но» — не английское «no»
        ("Не надо предоплаты, но аванс 50% обязателен", True),
        ("Предоплата, не обсуждается", True),
        ("Не беру никакую предоплату", False),
        ("Работаю без предоплаты и не беру аванс", False),
        ("Предоплаты нет", False),
        ("prepayment is not required", False),
        ("Radim bez avansa, ne brinite", False),
        # отрицание из другой фразы — не отрицание
        ("Не волнуйтесь, предоплата всего 30%", True),
        ("Nema problema, avans 30% pa dolazim", True),
        ("Без проблем, предоплата 50% на карту", True),
        ("No worries, deposit is only 20%", True),
        ("Не забудьте про предоплату", True),
        ("Предоплата, нет проблем", True),
        # двойное отрицание дальше во фразе
        ("Без предоплаты никак", True),
        ("Без предоплаты мы к сожалению не выезжаем", True),
        # местоимение и буква-двойник
        ("Переведите мне на карту 500", True),
        ("Уплатите мне унапред", True),
        ("Нужна пpедоплата 30%", True),
        # узкие основы: закуски, каперсы, кино
        ("zalogaji i zalogajnica", False),
        ("kaparima", False),
        ("завдати шкоди", False),
        ("kino karte", False),
        ("залог успеха", False),
        ("Объясню страдательный залог", False),
        # между отрицанием и словом — определитель или глагол
        ("Without any deposit", False),
        ("Работаю без всякой предоплаты", False),
        ("Без какой-либо предоплаты", False),
        ("Radim bez ikakvog avansa", False),
        ("Не нужно вносить предоплату", False),
        ("Ne morate plaćati unapred", False),
        ("No need to pay in advance", False),
        ("Nije potrebno da plaćate unapred", False),
        ("We never take a deposit", False),
        # однородные слова наследуют отрицание
        ("Работаю без предоплаты и залога", False),
        ("Bez avansa i depozita", False),
        ("No deposit or prepayment", False),
        ("No deposit and I do not charge for travel", False),
        # согласование и отказ после слова — не двойное отрицание
        ("Никаких авансов не требую", False),
        ("Nikakav avans ne treba", False),
        ("Предоплата: не нужна", False),
        ("Avans: nije potreban", False),
        ("Deposit: not required", False),
        ("Deposit is not charged", False),
        ("Не потрібна передоплата", False),
        ("Передоплата не потрібна", False),
        ("Аванс не прошу", False),
        ("Avans ne tražim", False),
        ("Работаю без предоплаты и не беру денег за выезд", False),
        # отказ ехать через запятую, тире и вводное слово
        ("Без предоплаты, к сожалению, не выезжаю", True),
        ("Bez avansa, nažalost, ne dolazim", True),
        ("Без предоплаты — не работаю", True),
        ("Без передоплати, на жаль, не приїжджаю", True),
        ("Bez avansa nikako", True),
        ("Without deposit I will not come", True),
        ("Нужна п\u03c1едоплата", True),  # греческая «ρ»
    ],
)
def test_prepayment_respects_negation_and_narrow_stems(text: str, asks: bool) -> None:
    assert find_prepayment(text) is asks


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
    # невидимые символы, ударение, двойники букв, транслит
    assert skeleton("закла\u200bдчик") == skeleton("закладчи\u0301к") == "zakladcik"
    assert skeleton("zakladchik") == skeleton("закладчик")
    assert skeleton("k\u03bfkain") == "kokain"  # греческая «ο»
    assert (
        skeleton("p. r. e. d. o. p. l. a. t. a") == skeleton("п/р/е/д/о/п/л/а/т/а") == "predoplata"
    )
    # число остаётся числом: цифры — буквы только среди букв
    assert skeleton("3000р 50e 100к") == "3000r 50e 100k"
    assert skeleton("h3r01n") == "heroin"
    # слово из двух письменностей: двойники — к письменности большинства
    assert skeleton("пpедоплата") == skeleton("npeдоплата") == "predoplata"
    assert skeleton("Best сasino") == "best casino"
    assert skeleton("з+а+к+л+а+д") == "zaklad"
    assert skeleton("Я и в субботу") == "ja i v subotu"  # три однобуквенных слова — не слово
    # греческие двойники в кириллическом слове
    assert skeleton("п\u03c1едоплата") == "predoplata"
    assert skeleton("ка\u03c1ту") == "kartu"
    assert skeleton("Ге\u03c1оин") == "geroin"
    assert skeleton("\u03c7акер") == "haker"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Pogledaj https://Bit.ly/3xYz i www.example.rs/katalog", ("bit.ly", "example.rs")),
        ("пиши: t . me/sosed_help или wa.me/381641234567", ("t.me", "wa.me")),
        ("scam-shop [.] com/pay", ("scam-shop.com",)),
        ("почта ivan (at) mail точка ru", ("mail.ru",)),
        ("viber://chat?number=381641234567 и @ivan_petrov", ()),
        ("Цена 1.500 дин, срок 12.10.2026", ()),
        ("https://evil@bit.ly/x и https://x:y@bit.ly/abc", ("bit.ly",)),
        ("ｂｉｔ.ｌｙ/abc", ("bit.ly",)),
        ("bit。ly/abc", ("bit.ly",)),
        ("tiny\u200burl.com/abc", ("tinyurl.com",)),
    ],
)
def test_domains_of_links_and_emails(text: str, expected: tuple[str, ...]) -> None:
    assert find_domains(text) == expected


def test_luhn() -> None:
    assert luhn_valid("4111111111111111")
    assert not luhn_valid("4111111111111112")


# --- калибровка 6.7: известные пробелы до примеров K28 -----------------------------------------
# Каждый случай — истинное срабатывание или истинное молчание; xfail — пробел, который не закрыть
# без потерь в соседних случаях: его решаем на реальных примерах K28.


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # зона-слово без пути — адрес в конце текста и перед знаком препинания
        ("Sajt: majstor.me", [(LINK, "majstor.me")]),
        ("Pogledajte majstor.me, tu je sve", [(LINK, "majstor.me")]),
        # обычная зона в любом регистре: с прописной её пишут и сайты, и автозамена
        ("Moj sajt je Majstor.Rs", [(LINK, "Majstor.Rs")]),
        ("pišite na ivan@gmail.Com", [(EMAIL, "ivan@gmail.Com")]),
        # страницы «все мои контакты» — ссылка и без пути
        ("Sve je na linktr.ee/ivan_majstor", [(LINK, "linktr.ee/ivan_majstor")]),
        ("Moji kontakti: Linktr.ee", [(LINK, "Linktr.ee")]),
        ("taplink.cc/ivan", [(LINK, "taplink.cc/ivan")]),
        # сотни и 10–19 словами, вперемешку с цифрами: 064 123 45 67, 064 623 45 67, 8 916 …
        (
            "nula šezdeset četiri sto dvadeset tri 45 67",
            [(PHONE, "nula šezdeset četiri sto dvadeset tri 45 67")],
        ),
        (
            "nula šezdeset četiri šest stotina dvadeset tri 45 67",
            [(PHONE, "nula šezdeset četiri šest stotina dvadeset tri 45 67")],
        ),
        (
            "нула шездесет четири сто двадесет три 45 67",
            [(PHONE, "нула шездесет четири сто двадесет три 45 67")],
        ),
        (
            "ноль шестьдесят четыре сто двадцать три сорок пять шестьдесят семь",
            [(PHONE, "ноль шестьдесят четыре сто двадцать три сорок пять шестьдесят семь")],
        ),
        ("0 шестьсот сорок один 23 45 67", [(PHONE, "0 шестьсот сорок один 23 45 67")]),
        ("8 девятьсот шестнадцать 123 45 67", [(PHONE, "8 девятьсот шестнадцать 123 45 67")]),
        # «što» перед номером словами — не сотня: ноль в сотню не входит, номер цел
        (
            "Što nula šest četiri jedan dva tri četiri pet šest sedam",
            [(PHONE, "nula šest četiri jedan dva tri četiri pet šest sedam")],
        ),
        pytest.param(
            "Pogledaj majstor.me i javi se",
            [(LINK, "majstor.me")],
            marks=pytest.mark.xfail(
                strict=True,
                reason="зона-слово посреди фразы — как «posao.to je sve»: решать на K28",
            ),
        ),
        pytest.param(
            "Majstor.Me",
            [(LINK, "Majstor.Me")],
            marks=pytest.mark.xfail(
                strict=True,
                reason="зона-слово с прописной — как «posao.To je sve», «televizor.TV»: K28",
            ),
        ),
        pytest.param(
            "nula šezdeset četiri sto dvadeset tri četiri hiljade petsto šezdeset sedam",
            [(PHONE, "nula šezdeset četiri sto dvadeset tri četiri hiljade petsto šezdeset sedam")],
            marks=pytest.mark.xfail(
                strict=True,
                reason="тысячи словами не разбираем: «četiri hiljade» в ценах чаще, чем в номерах",
            ),
        ),
    ],
)
def test_calibration_contacts_are_found(text: str, expected: list[tuple[ContactKind, str]]) -> None:
    assert found(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        # перечни часов и пунктов: каждое число на единицу больше предыдущего
        "Termini 08 09 10 11 12 h",
        "Stavke: 01 02 03 04 05",
        # после «00» идёт код страны, а он с нуля не начинается
        "Nalog 0000123456",
        # зона-слово посреди английской фразы и «at» без скобок перед ней
        "noon.to be honest",
        "See you at noon.to be honest",
        # «Info» с прописной — начало фразы после точки без пробела
        "Cena po dogovoru.Info na licu mesta",
        # сотни словами без номера рядом — просто числа
        "Imam sto dvadeset kvadrata",
        "Шестьсот сорок рублей за час",
        pytest.param(
            "Nalog 0012345678",
            marks=pytest.mark.xfail(
                strict=True,
                reason="«00» и код страны: номер документа не отличить от международного — K28",
            ),
        ),
    ],
)
def test_calibration_ordinary_text_is_left_alone(text: str) -> None:
    assert found(text) == []


@pytest.mark.parametrize(
    ("text", "asks"),
    [
        # сумма перед «на карту» — перевод вперёд (ru, sr латиницей и кириллицей)
        ("Скиньте 5000 на карту, и я выезжаю", True),
        ("1500 din na karticu pa dolazim", True),
        ("1500 дин на картицу па долазим", True),
        # сумма перед «заранее», «unapred», «унапред», в том числе процент и «тысяч»
        ("2000 заранее, остальное после работы", True),
        ("3000 dinara unapred", True),
        ("3000 динара унапред", True),
        ("50% unapred, ostatak posle", True),
        ("5 тысяч рублей заранее", True),
        # на карту после работы — оплата по факту
        ("5000 на карту после работы", False),
        ("1500 din na karticu nakon završetka", False),
        # сроки и часы «заранее» — не сумма
        ("Предупредите за 2 дня заранее", False),
        ("Javite se 24h unapred", False),
        ("Zakažite termin 2 dana unapred", False),
        # отрицание действует и на сумму
        ("Не нужно 5000 заранее", False),
        pytest.param(
            "Скидка 500 на карту лояльности",
            False,
            marks=pytest.mark.xfail(
                strict=True,
                reason="сумма перед «на карту» без глагола и срока — просьба вперёд чаще: K28",
            ),
        ),
    ],
)
def test_calibration_prepayment_sums(text: str, asks: bool) -> None:
    assert find_prepayment(text) is asks


def test_calibration_domains_fold_case_and_bio_hosts() -> None:
    assert find_domains("Sajt: Majstor.Rs i linktr.ee/ivan") == ("majstor.rs", "linktr.ee")


@pytest.mark.parametrize(
    "text",
    ["šest stotina " * 1_500, "шестьсот сорок " * 1_300, "majstor.me " * 1_800, "08 09 " * 3_300],
    ids=lambda text: text[:12],
)
def test_calibration_adversarial_input_is_linear(text: str) -> None:
    started = time.perf_counter()
    mask_contacts(text)
    find_domains(text)
    find_prepayment(text + " 5 tysjac rublej" * 1_000)
    assert time.perf_counter() - started < 3.0
