"""Контакты и просьбы о предоплате в тексте (ADR-0016 §3, ADR-0010, DEVELOPMENT_PLAN 2.4).

Shared kernel: чистые функции без БД. Им пользуются модерация (правила контента) и —
ниже неё по DAG — переписка (6.3a, скрытие контактов до договорённости), а ещё текст для
внешнего AI: туда контакты не уходят.

Что находит:
- телефоны: +381…, 00381…, 06x… — через пробелы, дефисы, точки, скобки; цифры словами на
  ru, uk, sr (обе письменности) и en («ноль шесть четыре», «nula šest»), «О» вместо нуля;
- номера карт: 13–19 цифр с верной контрольной суммой Луна;
- ссылки: http(s), www, домены с распространёнными зонами, t.me, wa.me, viber — и точки,
  спрятанные как «[.]», «(.)», « dot », « точка »;
- e-mail (в том числе «(at)», « собака »), @username Telegram.
Предоплату (`find_prepayment`) не маскируют: это сигнал для правил, а не контакт.

Даты («12.10.2026»), цены («1 000 000 RSD»), время и размеры телефоном не считаются:
телефон начинается с «+», «00» или «0» и набирает 8–15 цифр.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from app.platform.text.normalize import skeleton


class ContactKind(StrEnum):
    PHONE = "phone"
    CARD = "card"
    LINK = "link"
    EMAIL = "email"
    USERNAME = "username"


@dataclass(frozen=True, slots=True)
class Finding:
    kind: ContactKind
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Span:
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
_DIGIT_LOOKALIKES = str.maketrans({"o": "0", "о": "0", "l": "1", "і": "1", "|": "1"})
_TOKEN = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)
_SEPARATOR = re.compile(r"[\s\-.()/_·–—,]*")

_HIDDEN_DOT = r"(?:\s*[\[(]\s*\.\s*[\])]\s*|\s+(?:dot|точка|tačka|tacka|тачка)\s+)"
_DOT = rf"(?:\.|{_HIDDEN_DOT})"
"""Точка домена: обычная — без пробелов вокруг (иначе конец фразы «…me. Me» стал бы
доменом), спрятанная — «[.]», «(.)», « dot », « точка »."""
_TLD = (
    r"(?:rs|срб|com|net|org|ru|рф|ua|me|io|app|info|biz|eu|ba|hr|si|mk|de|at|ch|uk|us|co|"
    r"site|online|shop|store|link|ly|gl|gg|to|tv|xyz|top|pro|club|live|page|dev)"
)
_LINK = re.compile(
    rf"(?:https?://\S+|www{_DOT}\S+|\b(?:t|wa|telegram)\s*(?:\.|{_HIDDEN_DOT})\s*me\s*/\s*[\w+]+"
    rf"|viber://\S+"
    rf"|\b[\w\-]{{2,}}(?:{_DOT}[\w\-]{{2,}})*{_DOT}{_TLD}\b(?:/\S*)?)",
    re.IGNORECASE | re.UNICODE,
)
_AT = r"(?:\s*@\s*|\s*[\[(]\s*(?:at|собака)\s*[\])]\s*|\s+(?:собака|at)\s+)"
_EMAIL = re.compile(
    rf"\b[\w.+\-]+{_AT}[\w\-]+(?:{_DOT}[\w\-]+)*{_DOT}[a-zа-я]{{2,}}\b",
    re.IGNORECASE | re.UNICODE,
)
_USERNAME = re.compile(r"(?<![\w.])@\s?[A-Za-z][A-Za-z0-9_]{3,31}\b")
_DATE = re.compile(
    r"\b(\d{1,2})([./])(\d{1,2})\2(?:\d{4}|\d{2})\b"
    r"|\b(\d{1,2})-(\d{1,2})-\d{4}\b"
    r"|\b(\d{1,2})\.(\d{1,2})\.(?!\d)"
)
"""Даты «01.10.2026», «01/10/26», «01-10-2026», «1.10.» — не телефон, даже с нулём впереди.
Дефис — только с годом из четырёх цифр: «123-45-67» — это телефон."""

_PREPAYMENT = re.compile(
    r"\b(?:"
    # ru / uk: предоплата, аванс, залог, завдаток, «оплата заранее», «переведите на карту»
    r"pred?oplat\w*|peredoplat\w*|avans\w*|zalog\w*|zavdat\w*|kapar\w*|depozit\w*|predujam\w*"
    r"|(?:oplat|uplat|plat|plac)\w*\s+(?:zarane|vpered|unapred|unaprijed)"
    r"|(?:zarane|vpered|unapred|unaprijed)\s+(?:oplat|uplat|plat|plac)\w*"
    r"|(?:perevedit|perevedi|skin|skinte|kinte|kin)\w*\s+(?:na\s+)?(?:kart|sc[eo]t)\w*"
    # en
    r"|prepay\w*|pre\s?pay\w*|upfront|advance\s+payment|pay\s+(?:in\s+)?advance|deposit\w*"
    r")\b"
)
"""По скелету (normalize.py): «предоплата», «predoplata» и «пред0плата» — одно слово. В скелете
нет двойных букв: «заранее» — это «zarane»."""
_HIDDEN_DOT_RE = re.compile(_HIDDEN_DOT, re.IGNORECASE)
_AT_RE = re.compile(_AT, re.IGNORECASE)
_SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.IGNORECASE)
_HOST_END = re.compile(r"[/?#:\s]")


def find_contacts(text: str) -> tuple[Finding, ...]:
    """Контакты в тексте: непересекающиеся, по порядку."""
    found = [
        *_digit_runs(text),
        *(Finding(ContactKind.EMAIL, m.start(), m.end()) for m in _EMAIL.finditer(text)),
        *(Finding(ContactKind.LINK, m.start(), m.end()) for m in _LINK.finditer(text)),
        *(Finding(ContactKind.USERNAME, m.start(), m.end()) for m in _USERNAME.finditer(text)),
    ]
    found.sort(key=lambda f: (f.start, -(f.end - f.start)))
    result: list[Finding] = []
    for finding in found:
        if result and finding.start < result[-1].end:  # вложенное или пересекающееся
            continue
        result.append(finding)
    return tuple(result)


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


def find_prepayment(text: str) -> bool:
    """Просит ли текст предоплату, аванс или перевод на карту (ru, uk, sr, en)."""
    return _PREPAYMENT.search(skeleton(text)) is not None


def find_domains(text: str) -> tuple[str, ...]:
    """Домены ссылок и адресов почты в тексте — для правил модерации по доменам: нижний
    регистр, без www, спрятанные точки раскрыты («bit [.] ly/x» → «bit.ly»). Ссылки
    мессенджеров без домена (viber://) не входят."""
    domains: list[str] = []
    for finding in find_contacts(text):
        fragment = text[finding.start : finding.end]
        if finding.kind is ContactKind.EMAIL:
            fragment = _AT_RE.split(fragment, maxsplit=1)[-1]
        elif finding.kind is not ContactKind.LINK or fragment.lower().startswith("viber://"):
            continue
        fragment = re.sub(r"\s*\.\s*", ".", _HIDDEN_DOT_RE.sub(".", fragment))
        host = _HOST_END.split(_SCHEME.sub("", fragment.strip()), maxsplit=1)[0]
        host = host.casefold().strip(".").removeprefix("www.")
        if "." in host:
            domains.append(host)
    return tuple(dict.fromkeys(domains))


def luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value = value * 2 - 9 if value > 4 else value * 2
        total += value
    return total % 10 == 0


@dataclass(frozen=True, slots=True)
class _Piece:
    digits: str
    start: int
    end: int


def _digit_runs(text: str) -> list[Finding]:
    """Телефоны и карты: цифры (и цифры словами), идущие подряд через разделители. Даты
    заменяются пробелами той же длины: позиции остальных находок не сдвигаются."""
    text = _DATE.sub(_blank_date, text)
    findings: list[Finding] = []
    run: list[_Piece] = []
    tens: _Piece | None = None  # «шестьдесят» ждёт единицу
    previous_end = 0
    for match in _TOKEN.finditer(text):
        piece = _piece(match.group(), match.start(), match.end())
        gap = text[previous_end : match.start()]
        joined = bool(run or tens) and _SEPARATOR.fullmatch(gap) is not None
        if piece is None or not joined:
            if tens is not None:
                run.append(_Piece(tens.digits + "0", tens.start, tens.end))
                tens = None
            findings.extend(_classify(text, run))
            run = []
        if piece is None:
            previous_end = match.end()
            continue
        if tens is not None:
            if piece.digits.isdigit() and len(piece.digits) == 1 and _is_unit_word(match.group()):
                run.append(_Piece(tens.digits + piece.digits, tens.start, piece.end))
                tens = None
                previous_end = match.end()
                continue
            run.append(_Piece(tens.digits + "0", tens.start, tens.end))
            tens = None
        if match.group().casefold() in _TENS:
            tens = piece
        else:
            run.append(piece)
        previous_end = match.end()
    if tens is not None:
        run.append(_Piece(tens.digits + "0", tens.start, tens.end))
    findings.extend(_classify(text, run))
    return findings


def _blank_date(match: re.Match[str]) -> str:
    """Правдоподобная дата (день 1–31, месяц 1–12) — пробелы той же длины; иначе как есть."""
    day, month = next(
        (match.group(d), match.group(m)) for d, m in ((1, 3), (4, 5), (6, 7)) if match.group(d)
    )
    if 1 <= int(day) <= 31 and 1 <= int(month) <= 12:
        return " " * len(match.group())
    return match.group()


def _piece(token: str, start: int, end: int) -> _Piece | None:
    word = token.casefold()
    if word in _UNITS:
        return _Piece(_UNITS[word], start, end)
    if word in _TENS:
        return _Piece(_TENS[word], start, end)
    if any(char.isdigit() for char in word):
        digits = word.translate(_DIGIT_LOOKALIKES)  # «O64» — это 064
        if digits.isdigit():
            return _Piece(digits, start, end)
    return None


def _is_unit_word(token: str) -> bool:
    return token.casefold() in _UNITS


def _classify(text: str, run: list[_Piece]) -> list[Finding]:
    if not run:
        return []
    digits = "".join(piece.digits for piece in run)
    start, end = run[0].start, run[-1].end
    plus = text[max(0, start - 2) : start].strip().endswith("+")
    if plus:
        start = text.rindex("+", 0, start)
    if 13 <= len(digits) <= 19 and not plus and luhn_valid(digits):
        return [Finding(ContactKind.CARD, start, end)]
    if _phone(digits, plus=plus):
        return [Finding(ContactKind.PHONE, start, end)]
    return []


def _phone(digits: str, *, plus: bool) -> bool:
    if plus:
        return 8 <= len(digits) <= 15
    if digits.startswith("00"):
        return 10 <= len(digits) <= 15
    if digits.startswith("0"):
        return 8 <= len(digits) <= 11
    return digits.startswith("381") and 11 <= len(digits) <= 12
