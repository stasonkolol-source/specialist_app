"""Контакты и просьбы о предоплате в тексте (ADR-0016 §3, ADR-0010, DEVELOPMENT_PLAN 2.4).

Shared kernel: чистые функции без БД. Им пользуются модерация (правила контента) и —
ниже неё по DAG — переписка (6.3a, скрытие контактов до договорённости), а ещё текст для
внешнего AI: туда контакты не уходят.

Что находит:
- телефоны: +381…, 00381…, 06x…, 381…, 380…, российские 8 9xx… и 7 9xx… — через пробелы,
  дефисы, точки, скобки, «*», «|», «:», невидимые символы; цифры словами на ru, uk, sr (обе
  письменности) и en («ноль шесть четыре», «nula šest»), в том числе десятки, 10–19 и сотни
  («сто двадцать три», «šest stotina dvadeset»), «О» вместо нуля, полноширинные, надстрочные
  и «цифры в кружках». Телефон находится и внутри ряда чисел («Cena 3000 064 123 4567», «7 064
  123 4567»). Тысячи словами («četiri hiljade petsto…») не разбираем;
- номера карт: 13–19 цифр, первая — как у платёжных систем (2–6, 9), контрольная сумма Луна;
- счета сербских банков: 3-13-2 цифры с контрольным числом по модулю 97;
- ссылки: http(s), www, домены с распространёнными зонами, t.me, wa.me, viber, страницы «все
  мои контакты» (linktr.ee, taplink.cc …) — и точки, спрятанные как «[.]», «(.)», «[dot]»,
  « dot », « точка »;
- e-mail (в том числе «(at)», « собака », «ivan@gmail» без зоны у известных сервисов),
  @username Telegram (и «tg @ ivan», «tg: ivan_master» после названия мессенджера);
- IBAN (по модулю 97).
Предоплату (`find_prepayment`) не маскируют: это сигнал для правил, а не контакт.

Даты («12.10.2026»), время в диапазонах и после предлогов («08.00-16.00», «с 9:00»), цены
(«1 000 000 RSD», «1000, 1200, 1800 din», «2000 2500 3000 3500»), размеры («0 60 120 180»),
перечни («Termini 08 09 10 11 12 h», «Stavke: 01 02 03 04 05») и номера документов с «000»
(«Nalog 0000123456») телефоном, картой и счётом не считаются. «posao.To je sve» и «posao.to
je sve» — не ссылки: зона-слово (.to, .si, .de, .me …) — ссылка только строчными и только с
путём («majstor.me/x») или в конце текста и перед знаком препинания («Sajt: majstor.me»);
посреди фразы («pogledaj majstor.me i javi se») её не отличить от конца предложения без
пробела. Остальные зоны — в любом регистре («Majstor.Rs», «ivan@gmail.Com»), кроме «Info».
«I'm @ home» и «see you at noon.to be honest» — не контакты.

Позиции находок — в исходном тексте. Поиск идёт по свёрнутому тексту: невидимые символы и
надстрочные знаки удалены, буква с разложенной диакритикой собрана, каждый символ — в форме
NFKC («０» → «0», «¹» → «1», «ｂ» → «b»); карта индексов переводит находку обратно. Время —
линейное от длины текста: регулярные выражения начинают совпадение только в начале цепочки
и не перебирают её заново.
"""

import re
import unicodedata
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from itertools import pairwise

from app.platform.text.normalize import clauses, skeleton


class ContactKind(StrEnum):
    PHONE = "phone"
    CARD = "card"
    ACCOUNT = "account"
    LINK = "link"
    EMAIL = "email"
    USERNAME = "username"


@dataclass(frozen=True, slots=True)
class Finding:
    kind: ContactKind
    start: int
    end: int


MASK = "•••"

_UNITS = {
    # ru
    "ноль": "0", "нуль": "0", "один": "1", "одна": "1", "два": "2", "две": "2",
    "три": "3", "четыре": "4", "пять": "5", "шесть": "6", "семь": "7", "восемь": "8",
    "девять": "9",
    # uk
    "дві": "2", "чотири": "4", "п'ять": "5", "шість": "6", "сім": "7", "вісім": "8",
    "дев'ять": "9",
    # sr
    "нула": "0", "један": "1", "једна": "1", "четири": "4", "пет": "5", "шест": "6",
    "седам": "7", "осам": "8", "девет": "9", "nula": "0", "jedan": "1", "jedna": "1",
    "dva": "2", "dve": "2", "tri": "3", "četiri": "4", "cetiri": "4", "pet": "5",
    "šest": "6", "sest": "6", "sedam": "7", "osam": "8", "devet": "9",
    # en
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}  # fmt: skip
_TENS = {
    "двадцать": "2", "тридцать": "3", "сорок": "4", "пятьдесят": "5", "шестьдесят": "6",
    "семьдесят": "7", "восемьдесят": "8", "девяносто": "9",
    "двадцять": "2", "тридцять": "3", "п'ятдесят": "5", "шістдесят": "6",
    "сімдесят": "7", "вісімдесят": "8", "дев'яносто": "9",
    "двадесет": "2", "тридесет": "3", "четрдесет": "4", "педесет": "5", "шездесет": "6",
    "седамдесет": "7", "осамдесет": "8", "деведесет": "9",
    "dvadeset": "2", "trideset": "3", "četrdeset": "4", "cetrdeset": "4", "pedeset": "5",
    "šezdeset": "6", "sezdeset": "6", "sedamdeset": "7", "osamdeset": "8",
    "devedeset": "9",
    "twenty": "2", "thirty": "3", "forty": "4", "fifty": "5", "sixty": "6",
    "seventy": "7", "eighty": "8", "ninety": "9",
}  # fmt: skip
"""Десятки словами: «шестьдесят четыре» — 64, «шестьдесят» перед не-единицей — 60."""
_TEENS = {
    "десять": "10", "одиннадцать": "11", "двенадцать": "12", "тринадцать": "13",
    "четырнадцать": "14", "пятнадцать": "15", "шестнадцать": "16", "семнадцать": "17",
    "восемнадцать": "18", "девятнадцать": "19",
    "одинадцять": "11", "дванадцять": "12", "тринадцять": "13", "чотирнадцять": "14",
    "п'ятнадцять": "15", "шістнадцять": "16", "сімнадцять": "17", "вісімнадцять": "18",
    "дев'ятнадцять": "19",
    "десет": "10", "једанаест": "11", "дванаест": "12", "тринаест": "13", "четрнаест": "14",
    "петнаест": "15", "шеснаест": "16", "седамнаест": "17", "осамнаест": "18",
    "деветнаест": "19",
    "deset": "10", "jedanaest": "11", "dvanaest": "12", "trinaest": "13", "četrnaest": "14",
    "cetrnaest": "14", "petnaest": "15", "šesnaest": "16", "sesnaest": "16",
    "sedamnaest": "17", "osamnaest": "18", "devetnaest": "19",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
    "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18", "nineteen": "19",
}  # fmt: skip
"""От 10 до 19 словами — две цифры сразу: «сто двенадцать» — 112."""
_HUNDREDS = {
    "сто": "1", "двести": "2", "триста": "3", "четыреста": "4", "пятьсот": "5",
    "шестьсот": "6", "семьсот": "7", "восемьсот": "8", "девятьсот": "9",
    "двісті": "2", "чотириста": "4", "п'ятсот": "5", "шістсот": "6", "сімсот": "7",
    "вісімсот": "8", "дев'ятсот": "9",
    "двеста": "2", "двјеста": "2", "четиристо": "4", "петсто": "5", "шестсто": "6",
    "седамсто": "7", "осамсто": "8", "деветсто": "9",
    "sto": "1", "dvesta": "2", "dvjesta": "2", "trista": "3", "četiristo": "4",
    "cetiristo": "4", "petsto": "5", "šeststo": "6", "seststo": "6", "sedamsto": "7",
    "osamsto": "8", "devetsto": "9",
}  # fmt: skip
"""Сотни словами: «шестьсот сорок один» — 641, «шестьсот» перед не-числом — 600. «sto» — это и
сербское «što»: ноль после сотни поэтому в неё не входит («Što nula šest četiri…» — номер)."""
_HUNDRED = frozenset({"stotina", "stotine", "стотина", "стотине", "hundred", "hundreds"})
"""Сотня после единицы словом: «šest stotina» — 600, «six hundred forty» — 640."""
MIN_COUNTING = 4
"""Столько чисел подряд, каждое на единицу больше предыдущего, — перечень, а не номер."""
_DIGIT_LOOKALIKES = str.maketrans({"o": "0", "о": "0", "l": "1", "і": "1", "|": "1"})
_TOKEN = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)
_SEPARATOR_CHARS = r"\s\-.()/_·–—*|:'’‐‑‒―−•∙⋅~"
_SEPARATOR = re.compile(rf"[{_SEPARATOR_CHARS}]*")
"""Между цифрами одного номера. Запятой нет: «1000, 1200, 1800» — это цены, а не карта."""
_SPELLED_SEPARATOR = re.compile(rf"[{_SEPARATOR_CHARS},]*")
"""Рядом с цифрой словом или одиночной цифрой можно и запятую: «nula šest četiri, jedan dva
tri, 4567» и «0, 6, 4, 1…» — это номер по цифре. Между многозначными числами — нельзя."""
MAX_PHONE_DIGITS = 15
MAX_RUN_DIGITS = 19
"""Длиннее внутри ряда ничего не ищем: у карты — до 19 цифр, у телефона — до 15."""
MAX_PREPAYMENT_TEXT = 20_000
"""Предоплату ищем в начале текста такой длины: тексты продукта короче, дальше — мусор."""
CARD_PREFIXES = frozenset("234569")
CARD_GROUP = 4
"""Первая цифра карты: Mastercard 2, Amex и JCB 3, Visa 4, Mastercard 5, Maestro и UnionPay
6, DinaCard 9."""
ACCOUNT_DIGITS = 18
"""Счёт сербского банка: банк (3), номер (13, с нулями впереди), контрольное число (2)."""
_COUNTRY_CODES = frozenset({"380", "381", "382", "385", "386", "387", "389"})
"""Код страны без «+»: Сербия и соседи, Украина — 11–12 цифр вместе с кодом."""

_HIDDEN_DOT = (
    r"(?:\s{0,3}[\[(]\s{0,3}(?:\.|dot|точка|tačka|tacka|тачка)\s{0,3}[\])]\s{0,3}"
    r"|\s{1,3}(?:dot|точка|tačka|tacka|тачка)\s{1,3})"
)
_DOT = rf"(?:\.|{_HIDDEN_DOT})"
"""Точка домена: обычная — без пробелов вокруг (иначе конец фразы «…me. Me» стал бы
доменом), спрятанная — «[.]», «(.)», «[dot]», « dot », « точка »."""
_TLDS = (
    "rs", "срб", "com", "net", "org", "ru", "рф", "ua", "biz", "eu", "ba", "hr", "mk", "xyz",
)  # fmt: skip
"""Зоны, которые не спутать с обычным словом, — в любом регистре: «Majstor.Rs», «gmail.Com»."""
_LOWER_TLDS = ("info",)
"""«Info» с прописной — частое начало фразы после точки без пробела («dogovoru.Info na
064…»): эта зона — только строчными."""
_WORD_TLDS = (
    "me", "io", "app", "si", "de", "at", "ch", "uk", "us", "co", "site", "online", "shop",
    "store", "link", "ly", "gl", "gg", "to", "tv", "top", "pro", "club", "live", "page", "dev",
)  # fmt: skip
"""Зоны-слова и частые сокращения («sam.si li tu», «posao.to je sve»): ссылка — с путём или в
конце текста и перед знаком препинания («Sajt: majstor.me», «majstor.me, zovite»)."""
_BIO_HOSTS = (
    "linktr.ee", "taplink.cc", "taplink.ws", "taplink.at", "lnk.bio", "beacons.ai", "carrd.co",
    "hipolink.me", "mssg.me",
)  # fmt: skip
"""Страницы «все мои контакты» (link in bio): ссылка и без пути, в любом месте текста. Их зоны
(.ee, .cc, .ai, .bio) целиком в списки выше не входят: «bio» — сербское слово («posao.bio je
težak»), остальные в пилотной зоне редки — решать на примерах K28."""
_TLD = "(?:(?i:" + "|".join(_TLDS) + ")|(?-i:" + "|".join(_LOWER_TLDS) + "))"
_WORD_TLD = "(?-i:" + "|".join(_WORD_TLDS) + ")"
_TLD_UPPER = (
    "(?-i:"
    + "|".join(tld.upper() for tld in (*_TLDS, *_LOWER_TLDS, *_WORD_TLDS) if tld.isascii())
    + ")"
)
_ANY_TLD = f"(?:{_TLD}|{_WORD_TLD})"
_TEXT_END = r"(?=[ \t]{0,3}(?:[\n\r,;:!?)\]»\"'…]|\.(?!\w)|$))"
"""Конец текста, строки или знак препинания после адреса: «posao.to je sve» — фраза идёт
дальше, «Sajt: majstor.me» и «majstor.me, zovite» — адрес."""
_LABEL = r"[\w\-]++"
_LABELS = 8
"""Частей домена до зоны — не больше 8 (a.b.majstor.co.rs — четыре): иначе на «x[.]x[.]…»
каждое совпадение перебирало бы всю цепочку (квадратичное время)."""
_START = r"(?<![\w\-.])"
"""Совпадение начинается только в начале цепочки «слово-слово.слово»: без этого поиск на
«a-a-a-…» перебирал бы цепочку с каждой буквы (квадратичное время)."""
_HOST = rf"{_START}{_LABEL}(?:{_DOT}{_LABEL}){{0,{_LABELS}}}{_DOT}"
_BIO_HOST = "|".join(
    rf"{re.escape(label)}{_DOT}{re.escape(zone)}"
    for label, zone in (host.split(".") for host in _BIO_HOSTS)
)
_LINK = re.compile(
    rf"https?://\S+|www{_DOT}\S+"
    rf"|\b(?:t|wa|telegram)(?:\s{{0,3}}\.\s{{0,3}}|{_HIDDEN_DOT})me\s{{0,3}}/\s{{0,3}}[\w+]+"
    rf"|viber://\S+"
    rf"|{_START}(?:{_BIO_HOST})(?![\w\-])(?:/\S*)?"
    rf"|{_HOST}{_TLD}(?![\w\-])(?:/\S*)?"
    rf"|{_HOST}{_WORD_TLD}/\S+"
    rf"|{_HOST}{_WORD_TLD}{_TEXT_END}"
    rf"|{_START}(?-i:[A-Z0-9\-]++(?:\.[A-Z0-9\-]++){{0,{_LABELS}}}\.){_TLD_UPPER}"
    rf"(?![\w\-])(?:/\S*)?",
    re.IGNORECASE | re.UNICODE,
)
_AT_SIGN = r"\s{0,3}@\s{0,3}"
_AT_BRACKETS = r"\s{0,3}[\[(]\s{0,3}(?:at|собака)\s{0,3}[\])]\s{0,3}"
_AT_BARE = r"\s{1,3}(?:собака|at)\s{1,3}"
_AT_WORD = rf"(?:{_AT_BRACKETS}|{_AT_BARE})"
_LOCAL = r"(?:[\w.+\-]|\[\.\]|\(\.\))++"
"""Имя почты, в том числе с точкой в скобках: «ivan[.]petrov@gmail.com»."""
"""Пробелы вокруг «@», «(at)» и спрятанной точки — не больше трёх: иначе находка тянулась бы
через тысячи пробелов, а разбор её фрагмента занимал бы квадратичное время."""
_AT = rf"(?:{_AT_SIGN}|{_AT_WORD})"
_DOMAIN_PART = rf"{_LABEL}(?:{_DOT}{_LABEL}){{0,{_LABELS}}}{_DOT}"
_EMAIL = re.compile(
    rf"(?<![\w.+\-])(?<!\[\.\])(?<!\(\.\)){_LOCAL}"
    rf"(?:{_AT_SIGN}{_DOMAIN_PART}(?:{_TLD}(?![\w\-])|(?-i:[a-zа-я]{{2,}}|[A-Z]{{2,}}))"
    rf"|{_AT_BRACKETS}{_DOMAIN_PART}{_ANY_TLD}"
    rf"|{_AT_BARE}{_DOMAIN_PART}{_TLD})(?![\w\-])",
    re.IGNORECASE | re.UNICODE,
)
"""Адрес со словом вместо «@» («ivan собака mail точка ru») — только с известной зоной:
«Есть собака лабрадор.Нужен выгул» — не почта. Слово без скобок («ivan at gmail dot com») — и
зона не слово: «see you at noon.to be honest» — не почта. Зона из списка — в любом регистре
(«ivan@gmail.Com»), любая другая — строчными или прописными: «I'm @ home.Please» — не почта."""
_HANDLE = r"[A-Za-z](?:[A-Za-z0-9_]|\.(?=[A-Za-z0-9_])){3,31}"
"""Ник: латиница, цифры, «_» и точка внутри (Instagram: «ivan.master»)."""
_USERNAME = re.compile(rf"(?<![\w.])@{_HANDLE}\b")
_MESSENGER = (
    r"(?i:\b(?:tg|telegram|телеграм\w*|телег\w*|тг|viber|вайбер\w*|insta\w*|инст\w*|whatsapp"
    r"|ватсап\w*|вотсап\w*))"
)
_MESSENGER_USERNAME = re.compile(
    rf"{_MESSENGER}\W{{0,3}}?(@\s{{1,3}}{_HANDLE})\b"
    rf"|{_MESSENGER}\s{{0,3}}[:\-–—]\s{{0,3}}([A-Za-z](?:[A-Za-z0-9_]|\.(?=\w)){{4,31}})\b"
    rf"|{_MESSENGER}\s{{1,3}}([A-Za-z][A-Za-z0-9]*[0-9_][A-Za-z0-9_]*)\b"
)
"""Ник после названия мессенджера: «tg @ ivan_master», «tg: ivan_master», «telegram
ivan_master99». Без «@» и двоеточия — только ник с цифрой или «_»: «telegram premium» — не ник."""
_EMAIL_NO_ZONE = re.compile(
    r"(?<![\w.+\-])[\w.+\-]++\s{0,3}@\s{0,3}(?i:gmail|googlemail|yahoo|outlook|hotmail|live|icloud|mail"
    r"|yandex|ya|proton(?:mail)?|gmx|abv|ukr|inbox|list|bk|rambler|eunet|sbb|mts)(?![\w.\-])"
)
"""Почта без зоны «ivan.petrov@gmail»: у известных почтовых сервисов зона и не нужна человеку."""
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ \-]?[A-Z0-9]){11,30}\b")
"""IBAN (RS35 1600 0000 0012 3456 78): проверка — по модулю 97 (ISO 13616)."""
_DATE = re.compile(
    r"\b(\d{1,2})([./])(\d{1,2})\2(?:\d{4}|\d{2})\b"
    r"|\b(\d{1,2})-(\d{1,2})-\d{4}\b"
    r"|\b(\d{1,2})\.(\d{1,2})\.(?!\d)"
)
"""Даты «01.10.2026», «01/10/26», «01-10-2026», «1.10.» — не телефон, даже с нулём впереди.
Дефис — только с годом из четырёх цифр: «123-45-67» — это телефон."""
_CLOCK = r"(?:[01]?\d|2[0-3])[.:][0-5]\d"
_TIME_RANGE = re.compile(rf"(?<![\d.:]){_CLOCK}\s{{0,3}}[-–—]\s{{0,3}}{_CLOCK}(?![\d.:])")
_TIME_LIST = re.compile(rf"(?<![\d.:]){_CLOCK}(?:\s{{0,3}}[,/;]?\s{{0,3}}{_CLOCK})+(?![\d.:])")
_TIME_AFTER = re.compile(
    rf"\b(?:od|do|с|до|в|u|at|from|to|until|posle|после|nakon|oko|около|around|after|before"
    rf"|pre|перед)\s{{1,3}}({_CLOCK})(?![\d.:])",
    re.IGNORECASE,
)
_TIME_UNIT = re.compile(
    rf"(?<![\d.:])({_CLOCK})(?=\s{{0,3}}(?:h|ч|часов|časova|casova|sati|сати)\b)",
    re.IGNORECASE,
)
"""Время — в диапазоне («08.00-16.00», «01.10-05.10»), перечнем («09:00 10:30 12:00»), после
предлога («с 9:00», «od 07.30») или с «ч»/«h». Отдельно стоящее «12:34» может быть частью номера
(«064 123 12:34»)."""

_PRONOUN = r"(?:(?:mne|nam|mi|meni|nama|me|us|to|ti|vam|vama|tebe)\s+)?"
"""«Переведите мне на карту», «уплатите нам унапред»: местоимение между глаголом и целью."""
_CURRENCY = (
    r"(?:din\w*|rsd|e|eur\w*|evr\w*|r|rub\w*|grn|griv\w*|hrn|usd|dolar\w*|k|tys\w*|tis\w*"
    r"|hiljad\w*)"
)
_SUM = rf"\d+(?:k|e|r|eur|din|rsd|rub)?(?:\s+{_CURRENCY}){{0,2}}"
"""Сумма в скелете: «5000», «50e», «2к», «3000 dinara», «5 тысяч рублей»; «50%» — это «50».
Единицы времени — не валюта: «2 дня заранее», «24h unapred» — не предоплата."""
_AFTER_THE_JOB = r"(?:\s+\w+){0,2}?\s+(?:posle|poslije|pisl\w*|nakon|after|po\s+(?:faktu|zavrs\w*))"
"""«5000 на карту после работы», «na karticu nakon završetka» — оплата по факту, а не вперёд."""
_PREPAYMENT = re.compile(
    r"\b(?:"
    # ru / uk / sr: предоплата, аванс, залог, завдаток, капара, «оплата заранее»,
    # «переведите на карту», сумма перед «на карту» и «заранее»
    r"pred?oplat\w*|peredoplat\w*|avans\w*"
    r"|(?<!stradatelnyj )(?<!dejstvitelnyj )zalog(?:a|u|om|e)?\b(?! uspeh)"
    r"|zavdat(?:ok|ku|kom|ka)|kapar(?:a|e|u|om)|depozit\w*|predujam\w*"
    rf"|(?:oplat|uplat|plat|plac)\w*\s+{_PRONOUN}(?:zarane|vpered|unapred|unaprijed)"
    r"|(?:zarane|vpered|unapred|unaprijed)\s+(?:oplat|uplat|plat|plac)\w*"
    rf"|(?:perevedi\w*|skin\w*|kin(?:te|i|u)?)\s+{_PRONOUN}(?:na\s+)?(?:kart|sc[eo]t)\w*"
    rf"|{_SUM}\s+(?:zarane|vpered|unapred|unaprijed)"
    rf"|{_SUM}\s+na\s+(?:kartu|kartku|karticu|kartocku)\b(?!{_AFTER_THE_JOB})"
    # en
    r"|prepay\w*|pre\s?pay\w*|upfront|advance\s+payment|pay\s+(?:in\s+)?advance|deposit\w*"
    r")\b"
)
"""По скелету предложения (normalize.clauses): «предоплата», «predoplata» и «пред0плата» —
одно слово. В скелете нет двойных букв: «заранее» — это «zarane». Основы узкие: «zalogaj»,
«kaparima», «завдати шкоди», «kino karte», «страдательный залог» — не предоплата."""
_ENGLISH_KEYWORD = ("prepay", "pre pay", "upfront", "advance", "pay", "deposit")


def _skeletons(words: Iterable[str]) -> frozenset[str]:
    """Слова списков ниже — в той же форме, что скелет текста: «need» там — «ned»."""
    return frozenset(skeleton(word) for word in words)


_NEGATORS = _skeletons(
    {"bez", "ne", "ni", "net", "nema", "nije", "nisu", "nikada", "nikad", "nikogda", "not",
     "without", "never", "dont", "doesnt", "wont", "nikakoj", "nikakuju", "nikakih",
     "nikakogo", "nikakav", "nikakvu", "nikakve", "nikakvog", "nikakva", "nikakvi"}
)  # fmt: skip
"""Отрицание перед словом: «без предоплаты», «bez avansa», «никакой предоплаты», «without
deposit». Английское «no» — только перед английским словом: русское «но» в скелете — тоже «no»."""
_BETWEEN = _skeletons(
    {"any", "a", "an", "the", "to", "da", "vsjakoj", "vsjakij", "vsjakuju", "vsjakih",
     "vsjakogo", "kakoj", "kakuju", "kakih", "kakogo", "libo", "nibud", "ikakav", "ikakvog",
     "ikakve", "ikakva", "ikakvu", "ikakvi", "ikakvih",
     "beru", "berem", "beremo", "uzimam", "uzimamo", "trazim", "trazimo", "trebam", "treba",
     "trebuju", "trebuem", "trebuetsja", "nado", "nuzna", "nuzno", "nuzen", "nuzny",
     "potreban", "potrebna", "potrebno", "potrebni", "potribna", "potribno", "potriben",
     "morate", "moras", "moram", "mora", "prosu", "prosim", "primam", "primamo", "vnosit",
     "platit", "placat", "placati", "placate", "uplacivati", "uplatiti", "platiti",
     "take", "need", "needs", "require", "ask", "charge", "want", "accept", "pay", "make"}
)  # fmt: skip
"""Между отрицанием и словом: определители и глаголы «брать, просить, нужно, платить» — «без
всякой предоплаты», «не беру аванс», «не нужно вносить предоплату», «no need to pay in advance»."""
_CONJUNCTIONS = _skeletons({"i", "ili", "ni", "ta", "and", "or", "nor", "ani", "a"})
"""Однородные слова наследуют отрицание: «без предоплаты и залога», «no deposit or prepayment»."""
_NOT_NEEDED = re.compile(
    r"(?:je\s+|is\s+)?(?:ne|nije|nisu|not|isnt)\s+(?:nuzn|nuzen|treb|potreb|potrib|neophod"
    r"|obavez|objazat|required|neded|necesary|beru|prosu|uzimam|trazim|naplacuj|carge|take"
    r"|ask)"
    r"|neobjazat|neobavez|nepotreb"
)
"""Отрицание сразу после слова: «предоплата не нужна», «предоплату не беру», «avans nije
potreban», «prepayment is not required», «предоплата необязательна»."""
_DOUBLE_NEGATION = _skeletons(
    {"ne", "nece", "necu", "necemo", "not", "wont", "dont", "nisam", "nikak", "nikako"}
)
"""Требование: «bez avansa ne dolazim», «без предоплаты никак», «…мы не выезжаем». Только после
«без» и «without»: «никакой предоплаты не нужно» — это согласование, а не двойное отрицание."""
_NOT_A_REFUSAL = _skeletons(
    {"brinite", "brini", "brinuti", "volnujtes", "volnujsja", "perezivajte", "perezivaj",
     "bespokojtes", "sekirajte", "worry", "beru", "berem", "prosu", "uzimam", "uzimamo",
     "trazim", "trazimo", "naplacujem", "charge", "take", "ask"}
)  # fmt: skip
"""«Radim bez avansa, ne brinite», «без предоплаты и не беру денег за выезд» — не требование."""
AFTER_WORDS = 6
"""Сколько слов после ключа смотрим: «без предоплаты мы к сожалению не выезжаем» — «не»
четвёртое; дальше не смотрим, иначе предложение из тысяч повторов проверялось бы квадратично."""
BEFORE_WORDS = 5

_HIDDEN_DOT_RE = re.compile(_HIDDEN_DOT, re.IGNORECASE)
_SPACED_DOT = re.compile(r"\s{0,3}\.\s{0,3}")
_AT_RE = re.compile(_AT, re.IGNORECASE)
_SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.IGNORECASE)
_AUTHORITY_END = re.compile(r"[/?#\s]")
_MARKS = frozenset({"Mn", "Me"})


@dataclass(frozen=True, slots=True)
class ContactScan:
    findings: tuple[Finding, ...]
    domains: tuple[str, ...]


def scan_contacts(text: str, *, domains: bool = True) -> ContactScan:
    """Контакты и (если нужны правилам по доменам) их домены за один проход."""
    folded = _fold(text)
    found = _find_folded(folded.text)
    return ContactScan(
        findings=tuple(Finding(f.kind, *folded.span(f.start, f.end)) for f in found),
        domains=_domains(folded.text, found) if domains else (),
    )


def find_contacts(text: str) -> tuple[Finding, ...]:
    """Контакты в тексте: непересекающиеся, по порядку, позиции — в исходном тексте."""
    folded = _fold(text)
    return tuple(Finding(f.kind, *folded.span(f.start, f.end)) for f in _find_folded(folded.text))


def mask_contacts(text: str, mask: str = MASK) -> str:
    """Текст с контактами, заменёнными на `mask`: для переписки до договорённости и для
    внешнего AI (ADR-0016: туда контакты не уходят)."""
    out: list[str] = []
    position = 0
    for finding in find_contacts(text):
        out.append(text[position : finding.start])
        out.append(mask)
        position = finding.end
    out.append(text[position:])
    return "".join(out)


def find_domains(text: str) -> tuple[str, ...]:
    """Домены ссылок и адресов почты — для правил модерации по доменам: нижний регистр, без
    www, логина и порта, спрятанные точки раскрыты («bit [.] ly/x», «ｂｉｔ.ｌｙ» → «bit.ly»).
    Ссылки мессенджеров без домена (viber://) не входят."""
    folded = _fold(text).text
    return _domains(folded, _find_folded(folded))


def _domains(folded: str, found: Sequence[Finding]) -> tuple[str, ...]:
    domains: list[str] = []
    for finding in found:
        if finding.kind not in {ContactKind.LINK, ContactKind.EMAIL}:
            continue
        fragment = folded[finding.start : finding.end]
        if fragment.casefold().startswith("viber://"):
            continue
        fragment = _SPACED_DOT.sub(".", _HIDDEN_DOT_RE.sub(".", fragment))
        if finding.kind is ContactKind.EMAIL:
            fragment = _AT_RE.split(fragment)[-1]
        else:
            authority = _AUTHORITY_END.split(_SCHEME.sub("", fragment.strip()), maxsplit=1)[0]
            fragment = authority.rsplit("@", 1)[-1].split(":", 1)[0]  # без логина и порта
        host = fragment.casefold().strip(".").removeprefix("www.")
        if "." in host:
            domains.append(host)
    return tuple(dict.fromkeys(domains))


def find_prepayment(text: str) -> bool:
    """Просит ли текст предоплату, аванс или перевод на карту (ru, uk, sr, en).

    Смотрим по фразам: отрицание считается, только если прямо относится к слову («работаю
    без предоплаты», «не беру аванс», «avans nije potreban», «no upfront payment»). «Не
    волнуйтесь, предоплата 30%» и «нет проблем, предоплата» — просьба: отрицание в другой
    фразе. Двойное отрицание — тоже просьба: «bez avansa ne dolazim», «без предоплаты никак»."""
    return any(_asks_in_clause(words) for words in clauses(text[:MAX_PREPAYMENT_TEXT]))


def luhn_valid(digits: str) -> bool:
    if not digits.isascii() or not digits.isdecimal():
        return False
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value = value * 2 - 9 if value > 4 else value * 2
        total += value
    return total % 10 == 0


def account_valid(digits: str) -> bool:
    """Счёт сербского банка: 18 цифр, число по модулю 97 равно 1 (ISO 7064 MOD 97-10)."""
    return len(digits) == ACCOUNT_DIGITS and digits.isascii() and int(digits) % 97 == 1


def iban_valid(value: str) -> bool:
    """IBAN: страна, две контрольные цифры, счёт; перестановка в числа по модулю 97 равна 1."""
    compact = re.sub(r"[ \-]", "", value).upper()
    if not 15 <= len(compact) <= 34 or not compact.isascii() or not compact.isalnum():
        return False
    rotated = compact[4:] + compact[:4]
    return int("".join(str(int(char, 36)) for char in rotated)) % 97 == 1


# --- свёрнутый текст ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Folded:
    text: str
    starts: tuple[int, ...]
    ends: tuple[int, ...]
    """Для каждого символа свёрнутого текста — начало и конец его источника в исходном."""

    def span(self, start: int, end: int) -> tuple[int, int]:
        return self.starts[start], self.ends[end - 1]


def _fold(text: str) -> _Folded:
    """Текст для поиска: буква с надстрочными знаками — одна буква (латинская — без знаков),
    невидимые символы и знаки — удалены, каждый символ — в форме NFKC, «。» — точка."""
    if text.isascii():
        return _Folded(text, tuple(range(len(text))), tuple(range(1, len(text) + 1)))
    out: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    position = 0
    while position < len(text):
        end = position + 1
        while end < len(text) and unicodedata.category(text[end]) in _MARKS:
            end += 1
        for char in _fold_cluster(text[position:end]):
            out.append(char)
            starts.append(position)
            ends.append(end)
        position = end
    return _Folded("".join(out), tuple(starts), tuple(ends))


_INVISIBLE = frozenset("\u115f\u1160\u3164\uffa0\u2800")
"""Пустые буквы хангыля и пробел Брайля: выглядят как пробел, но не Cf — прятали бы номер."""


def _fold_cluster(cluster: str) -> str:
    # кэш — только для коротких кластеров: «Zalgo» из сотен знаков съел бы память воркера
    return _fold_short(cluster) if len(cluster) <= 4 else _fold_any(cluster)


@lru_cache(maxsize=4096)
def _fold_short(cluster: str) -> str:
    return _fold_any(cluster)


def _fold_any(cluster: str) -> str:
    head = cluster[0]
    if unicodedata.category(head) in {"Cf", "Mn", "Me"} or head in _INVISIBLE:
        return ""
    if head.isascii():
        return head  # «t.mé», «ivän»: знаки над латинской буквой не прячут адрес
    folded = unicodedata.normalize("NFKC", cluster)
    folded = "".join(char for char in folded if unicodedata.category(char) not in _MARKS)
    base = unicodedata.normalize("NFD", folded)
    if len(folded) == 1 and base[0].isascii() and base[0].isalpha():
        folded = base[0]  # «é», «č», «ŕ» — латинская основа
    return folded.replace("。", ".").replace("｡", ".")


def _find_folded(text: str) -> list[Finding]:
    found = [
        *_digit_runs(text),
        *(Finding(ContactKind.EMAIL, m.start(), m.end()) for m in _EMAIL.finditer(text)),
        *(Finding(ContactKind.LINK, m.start(), m.end()) for m in _LINK.finditer(text)),
        *(Finding(ContactKind.USERNAME, m.start(), m.end()) for m in _USERNAME.finditer(text)),
        *(
            Finding(ContactKind.USERNAME, m.start(group), m.end(group))
            for m in _MESSENGER_USERNAME.finditer(text)
            for group in (1, 2, 3)
            if m.group(group)
        ),
        *(Finding(ContactKind.EMAIL, m.start(), m.end()) for m in _EMAIL_NO_ZONE.finditer(text)),
        *(
            Finding(ContactKind.ACCOUNT, m.start(), m.end())
            for m in _IBAN.finditer(text)
            if iban_valid(m.group())
        ),
    ]
    found.sort(key=lambda f: (f.start, -(f.end - f.start)))
    result: list[Finding] = []
    for finding in found:
        if result and finding.start < result[-1].end:  # вложенное или пересекающееся
            last = result[-1]
            if finding.end > last.end:  # «majstor.rs/064 123 4567»: одна маска на оба
                result[-1] = Finding(last.kind, last.start, finding.end)
            continue
        result.append(finding)
    return result


# --- предоплата --------------------------------------------------------------------------------


def _asks_in_clause(words: str) -> bool:
    tokens = words.split()
    index = 0  # номер слова, с которого начинается совпадение
    scanned = 0
    previous: tuple[int, bool] | None = None  # последнее слово предыдущего ключа и его отрицание
    for match in _PREPAYMENT.finditer(words):
        index += words.count(" ", scanned, match.start())
        scanned = match.start()
        first, last = index, index + match.group().count(" ")
        english = match.group().startswith(_ENGLISH_KEYWORD)
        carried = previous is not None and previous[1] and _joined(tokens[previous[0] + 1 : first])
        negated = _negated(tokens, first, last, english=english, carried=carried)
        if not negated:
            return True
        previous = (last, negated)
    return False


def _joined(between: Sequence[str]) -> bool:
    """Между двумя словами-ключами — только союзы и определители: однородные члены."""
    return len(between) <= BEFORE_WORDS and all(
        word in _CONJUNCTIONS or word in _BETWEEN for word in between
    )


def _negated(tokens: Sequence[str], first: int, last: int, *, english: bool, carried: bool) -> bool:
    negator = _negator_before(tokens, first, english=english)
    after = tokens[last + 1 : last + 1 + AFTER_WORDS]
    if negator is not None:
        return not (negator in {"bez", "without"} and _double_negation(after))
    if carried:
        return True
    if after[:1] in (["net"], ["nema"]) and not (after[1:2] and after[1].startswith("problem")):
        return True  # «предоплаты нет (вообще)», но «предоплата, нет проблем» — просьба
    return _NOT_NEEDED.match(" ".join(after[:4])) is not None


def _negator_before(tokens: Sequence[str], first: int, *, english: bool) -> str | None:
    """Отрицание, которое прямо относится к слову: между ними только _BETWEEN."""
    for word in reversed(tokens[max(0, first - BEFORE_WORDS) : first]):
        if word in _NEGATORS or (english and word == "no"):
            return word
        if word not in _BETWEEN:
            return None
    return None


def _double_negation(after: Sequence[str]) -> bool:
    """«Не» дальше в предложении: «без предоплаты не выезжаю», «без предоплаты никак». Не
    считается «не», которое отрицает другое слово-предоплату («без предоплаты и не беру аванс»)
    или успокаивает («ne brinite»)."""
    for position, word in enumerate(after):
        if word not in _DOUBLE_NEGATION:
            continue
        ahead = after[position + 1 : position + 4]
        if ahead[:1] and ahead[0] in _NOT_A_REFUSAL:
            continue
        if _PREPAYMENT.search(" ".join(ahead)):
            continue
        return True
    return False


# --- телефоны, карты, счета --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Piece:
    digits: str
    start: int
    end: int
    spelled: bool = False
    """Цифра словом или одиночная цифра: после такой части номер идёт и через запятую."""
    word: bool = False
    """Число словами («ноль», «шестьдесят четыре»), а не цифрами."""


@dataclass(frozen=True, slots=True)
class _Open:
    """Число словами, которое ещё может продолжиться: «шестьсот» ждёт десятки и единицу,
    «шестьдесят» — единицу. `places` — сколько младших цифр ещё не названо."""

    piece: _Piece
    places: int

    def closed(self) -> _Piece:
        """Число как есть, недостающие цифры — нули: «шестьсот» — 600, «шестьдесят» — 60."""
        digits = self.piece.digits + "0" * self.places
        return _Piece(digits, self.piece.start, self.piece.end, spelled=True, word=True)

    def taking(self, word: str, piece: _Piece) -> _Open | None:
        """Число вместе со следующим словом («шестьсот» + «сорок», «шестьдесят» + «четыре»)
        или None, если слово его не продолжает."""
        if self.places == 2 and word in _TENS:
            return self._with(piece.digits, piece.end, places=1)
        if self.places == 2 and word in _TEENS:
            return self._with(piece.digits, piece.end, places=0)
        if word in _UNITS and (self.places == 1 or piece.digits != "0"):
            return self._with("0" * (self.places - 1) + piece.digits, piece.end, places=0)
        return None

    def _with(self, digits: str, end: int, *, places: int) -> _Open:
        merged = _Piece(self.piece.digits + digits, self.piece.start, end, spelled=True, word=True)
        return _Open(merged, places)


def _digit_runs(text: str) -> list[Finding]:
    """Телефоны, карты и счета: цифры (и цифры словами), идущие подряд через разделители. Даты
    и время заменяются пробелами той же длины: позиции остальных находок не сдвигаются."""
    text = _blank_times(_DATE.sub(_blank_date, text))
    findings: list[Finding] = []
    run: list[_Piece] = []
    number: _Open | None = None  # «шестьсот», «шестьдесят» ждут продолжения
    previous_end = 0
    for token, token_start, token_end in _subtokens(text):
        word = token.casefold()
        gap = text[previous_end:token_start]
        if word in _HUNDRED and number is None and _unit_before(run, gap):
            unit = run.pop()  # «šest stotina»: единица перед «сотней» — число сотен
            hundreds = _Piece(unit.digits, unit.start, token_end, spelled=True, word=True)
            number = _Open(hundreds, places=2)
            previous_end = token_end
            continue
        piece = _piece(token, token_start, token_end)
        last = number.piece if number is not None else (run[-1] if run else None)
        spelled = last is not None and piece is not None and (last.spelled or piece.spelled)
        separator = _SPELLED_SEPARATOR if spelled else _SEPARATOR
        joined = last is not None and separator.fullmatch(gap) is not None
        if piece is None or not joined:
            if number is not None:
                run.append(number.closed())
                number = None
            findings.extend(_classify(text, run))
            run = []
        if piece is None:
            previous_end = token_end
            continue
        if number is not None:
            longer = number.taking(word, piece)
            if longer is not None:
                number = longer if longer.places else None
                if not longer.places:
                    run.append(longer.closed())
                previous_end = token_end
                continue
            run.append(number.closed())
            number = None
        if word in _HUNDREDS:
            number = _Open(piece, places=2)
        elif word in _TENS:
            number = _Open(piece, places=1)
        else:
            run.append(piece)
        previous_end = token_end
    if number is not None:
        run.append(number.closed())
    findings.extend(_classify(text, run))
    return findings


def _unit_before(run: Sequence[_Piece], gap: str) -> bool:
    """Перед «stotina», «hundred» вплотную стоит единица словом: «šest stotina», «six hundred»."""
    return (
        bool(run)
        and run[-1].word
        and len(run[-1].digits) == 1
        and run[-1].digits != "0"
        and _SPELLED_SEPARATOR.fullmatch(gap) is not None
    )


_LOOKALIKE_DIGITS = frozenset("oOоОlLіІ|")


def _subtokens(text: str) -> Iterator[tuple[str, int, int]]:
    """Токены текста, где буквы и цифры разрезаны: «Tel064», «4567a», «№0641…» (NFKC даёт
    «No0641…») — номер отдельно. Буква-двойник цифры («O64», «064O123») остаётся в числе, если
    рядом с ней нет других букв."""
    for match in _TOKEN.finditer(text):
        token, offset = match.group(), match.start()
        if token.isdecimal() or not any(char.isdigit() for char in token):
            yield token, offset, match.end()
            continue
        digit = [_digit_like(token, index) for index in range(len(token))]
        start = 0
        for index in range(1, len(token) + 1):
            if index == len(token) or digit[index] != digit[start]:
                yield token[start:index], offset + start, offset + index
                start = index


def _digit_like(token: str, index: int) -> bool:
    char = token[index]
    if char.isdigit():
        return True
    if char not in _LOOKALIKE_DIGITS:
        return False
    neighbours = [token[i] for i in (index - 1, index + 1) if 0 <= i < len(token)]
    has_digit = any(n.isdigit() for n in neighbours)
    has_letter = any(n.isalpha() and n not in _LOOKALIKE_DIGITS for n in neighbours)
    return has_digit and not has_letter


def _blank_date(match: re.Match[str]) -> str:
    """Правдоподобная дата (день 1–31, месяц 1–12) — пробелы той же длины; иначе как есть."""
    day, month = next(
        (match.group(d), match.group(m)) for d, m in ((1, 3), (4, 5), (6, 7)) if match.group(d)
    )
    if 1 <= int(day) <= 31 and 1 <= int(month) <= 12:
        return " " * len(match.group())
    return match.group()


def _blank_times(text: str) -> str:
    for whole in (_TIME_RANGE, _TIME_LIST):
        text = whole.sub(lambda m: " " * len(m.group()), text)
    for pattern in (_TIME_AFTER, _TIME_UNIT):
        text = pattern.sub(_blank_group, text)
    return text


def _blank_group(match: re.Match[str]) -> str:
    """Совпадение как есть, кроме времени (группа 1): оно — пробелы той же длины."""
    whole, offset = match.group(), match.start(1) - match.start()
    return whole[:offset] + " " * len(match.group(1)) + whole[offset + len(match.group(1)) :]


def _piece(token: str, start: int, end: int) -> _Piece | None:
    word = token.casefold()
    if word in _UNITS:
        return _Piece(_UNITS[word], start, end, spelled=True, word=True)
    for words in (_TENS, _TEENS, _HUNDREDS):
        if word in words:
            return _Piece(words[word], start, end, spelled=True, word=True)
    if any(char.isdigit() for char in word):
        digits = word.translate(_DIGIT_LOOKALIKES).replace("'", "").replace("’", "")
        if digits and all(char.isdecimal() for char in digits):  # «²» и «⑴» — не цифры номера
            ascii_digits = "".join(str(unicodedata.decimal(c)) for c in digits)
            return _Piece(ascii_digits, start, end, spelled=len(ascii_digits) == 1)
    return None


def _classify(text: str, run: list[_Piece]) -> list[Finding]:
    """Ряд целиком — счёт, карта или телефон; иначе ищем их внутри ряда: к номеру приклеилось
    число («Cena 3000 064 123 4567», «064 123 4567 12»), к карте — срок или CVV («4111 … 12/28»)."""
    if not run:
        return []
    plus, start = _plus(text, run[0].start)
    kind = _kind(run, plus=plus, inner=False)
    if kind is not None:
        return [Finding(kind, start, run[-1].end)]
    findings: list[Finding] = []
    first = 0
    while first < len(run):
        plus, start = _plus(text, run[first].start)
        longest: tuple[int, ContactKind] | None = None
        length = 0
        for last in range(first, len(run)):
            length += len(run[last].digits)
            if length > MAX_RUN_DIGITS:
                break
            found = _kind(run[first : last + 1], plus=plus, inner=True)
            if found is not None:
                longest = (last, found)
        if longest is None:
            first += 1
            continue
        findings.append(Finding(longest[1], start, run[longest[0]].end))
        first = longest[0] + 1
    return findings


def _kind(pieces: Sequence[_Piece], *, plus: bool, inner: bool) -> ContactKind | None:
    """Что это за цифры: счёт, карта, телефон. Внутри ряда «00…» — не телефон: скорее номер
    счёта или документа."""
    digits = "".join(piece.digits for piece in pieces)
    if not plus and (account_valid(digits) or _short_account(pieces)):
        return ContactKind.ACCOUNT
    # внутри ряда карта пишется как карта: группами по 4 («4111 1111 …») или одним числом
    card_like = not inner or len(pieces) == 1 or len(pieces[0].digits) == CARD_GROUP
    if not plus and card_like and _card(digits, pieces):
        return ContactKind.CARD
    if inner and digits.startswith("00"):
        return None
    return ContactKind.PHONE if _phone(digits, pieces, plus=plus) else None


def _short_account(pieces: Sequence[_Piece]) -> bool:
    """Счёт без ведущих нулей в середине: «160-123456-54» — это 160-0000000123456-54."""
    if len(pieces) != 3:
        return False
    bank, number, control = (piece.digits for piece in pieces)
    if len(bank) != 3 or len(control) != 2 or not 1 <= len(number) <= 13:
        return False
    return account_valid(bank + number.zfill(13) + control)


def _plus(text: str, start: int) -> tuple[bool, int]:
    """Стоит ли «+» перед номером (через пробел) и откуда тогда начинается находка."""
    if text[max(0, start - 2) : start].strip().endswith("+"):
        return True, text.rindex("+", 0, start)
    return False, start


def _card(digits: str, run: Sequence[_Piece]) -> bool:
    if not 13 <= len(digits) <= 19 or digits[0] not in CARD_PREFIXES:
        return False
    if len(run) >= 3 and all(piece.digits.endswith("0") for piece in run):
        return False  # «2000 2500 3000 3500» — прайс, а не карта
    return luhn_valid(digits)


def _phone(digits: str, run: Sequence[_Piece], *, plus: bool) -> bool:
    if plus:
        return 8 <= len(digits) <= MAX_PHONE_DIGITS
    if _counting(run):
        return False
    if digits.startswith("00"):
        # «Nalog 0000123456»: после «00» идёт код страны, а он с нуля не начинается
        return 10 <= len(digits) <= MAX_PHONE_DIGITS and digits[2] != "0"
    if digits.startswith("0"):
        # «0 60 120 180» — размеры: одиночный ноль, дальше только круглые числа
        lone_zero = (
            run[0].digits == "0"
            and not run[0].word
            and len(run) > 1
            and len(run[1].digits) > 1
            and all(piece.digits.endswith("0") for piece in run[1:])
        )
        return 9 <= len(digits) <= 11 and not lone_zero
    if digits[:3] in _COUNTRY_CODES:
        return 11 <= len(digits) <= 12
    # Россия и Казахстан без «+»: 8 999 123-45-67, 7 999 123 45 67 (мобильные и города)
    return len(digits) == 11 and digits[0] in "78" and digits[1] in "3489"


def _counting(run: Sequence[_Piece]) -> bool:
    """«Termini 08 09 10 11 12 h», «Stavke: 01 02 03 04 05» — перечень часов или пунктов, а не
    номер: каждое число на единицу больше предыдущего. Номер так не пишут: «06 07 08 09 10» как
    телефон — потеря, на которую идём."""
    return (
        len(run) >= MIN_COUNTING
        and all(len(piece.digits) <= 2 for piece in run)
        and all(int(b.digits) == int(a.digits) + 1 for a, b in pairwise(run))
    )
