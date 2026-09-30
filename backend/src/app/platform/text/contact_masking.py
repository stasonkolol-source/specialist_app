"""Контакты и просьбы о предоплате в тексте (ADR-0016 §3, ADR-0010, DEVELOPMENT_PLAN 2.4).

Shared kernel: чистые функции без БД. Им пользуются модерация (правила контента) и —
ниже неё по DAG — переписка (6.3a, скрытие контактов до договорённости), а ещё текст для
внешнего AI: туда контакты не уходят.

Что находит:
- телефоны: +381…, 00381…, 06x…, 381…, 380…, российские 8 9xx… и 7 9xx… — через пробелы,
  дефисы, точки, скобки, «*», «|», «:», невидимые символы; цифры словами на ru, uk, sr (обе
  письменности) и en («ноль шесть четыре», «nula šest»), «О» вместо нуля, полноширинные,
  надстрочные и «цифры в кружках». Телефон находится и внутри ряда чисел («Cena 3000 064 123
  4567», «7 064 123 4567»);
- номера карт: 13–19 цифр, первая — как у платёжных систем (2–6, 9), контрольная сумма Луна;
- ссылки: http(s), www, домены с распространёнными зонами, t.me, wa.me, viber — и точки,
  спрятанные как «[.]», «(.)», «[dot]», « dot », « точка »;
- e-mail (в том числе «(at)», « собака »), @username Telegram.
Предоплату (`find_prepayment`) не маскируют: это сигнал для правил, а не контакт.

Даты («12.10.2026»), время и диапазоны («08.00-16.00», «01.10-05.10»), цены («1 000 000
RSD», «1000, 1200, 1800 din»), размеры телефоном и картой не считаются. «posao.To je sve» —
не ссылка: зона домена пишется строчными (или весь адрес — прописными). «I'm @ home» — не
@username: после «@» пробела не бывает.

Позиции находок — в исходном тексте: сравнение идёт по тексту, где каждый символ заменён
своей формой NFKC, если она из одного символа (полноширинная «０» → «0», «¹» → «1»), а
невидимые и надстрочные знаки — пробелом. Длина текста при этом не меняется. Время — линейное
от длины текста: регулярные выражения начинают совпадение только в начале цепочки и не
перебирают её заново.
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

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
_SEPARATOR = re.compile(r"[\s\-.()/_·–—*|:'’]*")
"""Между цифрами одного номера. Запятой нет: «1000, 1200, 1800» — это цены, а не карта."""
_SPELLED_SEPARATOR = re.compile(r"[\s\-.()/_·–—*|:'’,]*")
"""Рядом с цифрой словом или одиночной цифрой можно и запятую: «nula šest četiri, jedan dva
tri, 4567» и «0, 6, 4, 1…» — это номер по цифре. Между многозначными числами — нельзя."""
MAX_PHONE_DIGITS = 15
CARD_PREFIXES = frozenset("234569")
"""Первая цифра карты: Mastercard 2, Amex и JCB 3, Visa 4, Mastercard 5, Maestro и UnionPay
6, DinaCard 9."""
_COUNTRY_CODES = frozenset({"380", "381", "382", "385", "386", "387", "389"})
"""Код страны без «+»: Сербия и соседи, Украина — 11–12 цифр вместе с кодом."""

_HIDDEN_DOT = (
    r"(?:\s*[\[(]\s*(?:\.|dot|точка|tačka|tacka|тачка)\s*[\])]\s*"
    r"|\s+(?:dot|точка|tačka|tacka|тачка)\s+)"
)
_DOT = rf"(?:\.|{_HIDDEN_DOT})"
"""Точка домена: обычная — без пробелов вокруг (иначе конец фразы «…me. Me» стал бы
доменом), спрятанная — «[.]», «(.)», «[dot]», « dot », « точка »."""
_TLDS = (
    "rs", "срб", "com", "net", "org", "ru", "рф", "ua", "me", "io", "app", "info", "biz",
    "eu", "ba", "hr", "si", "mk", "de", "at", "ch", "uk", "us", "co", "site", "online", "shop",
    "store", "link", "ly", "gl", "gg", "to", "tv", "xyz", "top", "pro", "club", "live",
    "page", "dev",
)  # fmt: skip
_TLD = "(?-i:" + "|".join(_TLDS) + ")"
_TLD_UPPER = "(?-i:" + "|".join(tld.upper() for tld in _TLDS if tld.isascii()) + ")"
_LABEL = r"[\w\-]++"
_LABELS = 8
"""Частей домена до зоны — не больше 8 (a.b.majstor.co.rs — четыре): иначе на «x[.]x[.]…»
каждое совпадение перебирало бы всю цепочку (квадратичное время)."""
_START = r"(?<![\w\-.])"
"""Совпадение начинается только в начале цепочки «слово-слово.слово»: без этого поиск на
«a-a-a-…» перебирал бы цепочку с каждой буквы (квадратичное время)."""
_LINK = re.compile(
    rf"https?://\S+|www{_DOT}\S+|\b(?:t|wa|telegram)(?:\s*\.\s*|{_HIDDEN_DOT})me\s*/\s*[\w+]+"
    rf"|viber://\S+"
    rf"|{_START}{_LABEL}(?:{_DOT}{_LABEL}){{0,{_LABELS}}}{_DOT}{_TLD}(?![\w\-])(?:/\S*)?"
    rf"|{_START}(?-i:[A-Z0-9\-]++(?:\.[A-Z0-9\-]++){{0,{_LABELS}}}\.){_TLD_UPPER}"
    rf"(?![\w\-])(?:/\S*)?",
    re.IGNORECASE | re.UNICODE,
)
_AT_SIGN = r"\s*@\s*"
_AT_WORD = r"(?:\s*[\[(]\s*(?:at|собака)\s*[\])]\s*|\s+(?:собака|at)\s+)"
_AT = rf"(?:{_AT_SIGN}|{_AT_WORD})"
_EMAIL = re.compile(
    rf"(?<![\w.+\-])[\w.+\-]++"
    rf"(?:{_AT_SIGN}{_LABEL}(?:{_DOT}{_LABEL}){{0,{_LABELS}}}{_DOT}(?-i:[a-zа-я]{{2,}}|[A-Z]{{2,}})"
    rf"|{_AT_WORD}{_LABEL}(?:{_DOT}{_LABEL}){{0,{_LABELS}}}{_DOT}{_TLD})(?![\w\-])",
    re.IGNORECASE | re.UNICODE,
)
"""Адрес со словом вместо «@» («ivan собака mail точка ru») — только с известной зоной:
«Есть собака лабрадор.Нужен выгул» — не почта."""
_USERNAME = re.compile(r"(?<![\w.])@[A-Za-z][A-Za-z0-9_]{3,31}\b")
_DATE = re.compile(
    r"\b(\d{1,2})([./])(\d{1,2})\2(?:\d{4}|\d{2})\b"
    r"|\b(\d{1,2})-(\d{1,2})-\d{4}\b"
    r"|\b(\d{1,2})\.(\d{1,2})\.(?!\d)"
)
"""Даты «01.10.2026», «01/10/26», «01-10-2026», «1.10.» — не телефон, даже с нулём впереди.
Дефис — только с годом из четырёх цифр: «123-45-67» — это телефон."""
_TIME = re.compile(r"(?<![\d.:])(?:[01]?\d|2[0-3])[.:][0-5]\d(?![\d.:])")
"""Время и диапазоны «08.00-16.00», «с 9:00», «01.10-05.10»: отдельно стоящие «ЧЧ.ММ». Пары
внутри номера («064.12.34.56») не трогаем: перед ними точка."""

_PREPAYMENT = re.compile(
    r"\b(?:"
    # ru / uk / sr: предоплата, аванс, залог, завдаток, капара, «оплата заранее»,
    # «переведите на карту»
    r"pred?oplat\w*|peredoplat\w*|avans\w*|zalog(?:a|u|om|e)?\b(?! uspeh)"
    r"|zavdat(?:ok|ku|kom|ka)|kapar(?:a|e|u|om)|depozit\w*|predujam\w*"
    r"|(?:oplat|uplat|plat|plac)\w*\s+(?:zarane|vpered|unapred|unaprijed)"
    r"|(?:zarane|vpered|unapred|unaprijed)\s+(?:oplat|uplat|plat|plac)\w*"
    r"|(?:perevedi\w*|skin\w*|kin(?:te|i|u)?)\s+(?:na\s+)?(?:kart|sc[eo]t)\w*"
    # en
    r"|prepay\w*|pre\s?pay\w*|upfront|advance\s+payment|pay\s+(?:in\s+)?advance|deposit\w*"
    r")\b"
)
"""По скелету (normalize.py): «предоплата», «predoplata» и «пред0плата» — одно слово. В скелете
нет двойных букв: «заранее» — это «zarane». Основы узкие: «zalogaj», «kaparima», «завдати
шкоди», «kino karte» — не предоплата."""
_ENGLISH_KEYWORD = ("prepay", "pre pay", "upfront", "advance", "pay", "deposit")
_NEGATORS = frozenset(
    {"bez", "ne", "ni", "net", "nema", "nije", "nisu", "nikako", "nikada", "nikad", "nikogda",
     "not", "without", "never", "dont", "doesnt", "wont"}
)  # fmt: skip
"""Отрицание перед словом: «без предоплаты», «не беру аванс», «bez avansa», «without
deposit». Английское «no» — только перед английским словом: русское «но» в скелете — тоже «no»."""
_NOT_NEEDED = re.compile(
    r"(?:ne|nije|nisu|not|isnt|is not)\s+(?:nuzn|nuzen|treb|potreb|neophod|obavez|objazat"
    r"|required|needed|necessary)"
    r"|(?:net|nema)\b"
)
"""Отрицание после слова: «предоплата не нужна», «avans nije potreban», «prepayment not
required», «предоплаты нет»."""
_DOUBLE_NEGATION = frozenset({"ne", "nece", "necu", "not", "wont", "dont", "nisam"})
_WINDOW = 120
"""«Bez avansa ne dolazim», «без предоплаты не выезжаю» — это требование предоплаты."""

_HIDDEN_DOT_RE = re.compile(_HIDDEN_DOT, re.IGNORECASE)
_SPACED_DOT = re.compile(r"\s*\.\s*")
_AT_RE = re.compile(_AT, re.IGNORECASE)
_SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.IGNORECASE)
_AUTHORITY_END = re.compile(r"[/?#\s]")


def find_contacts(text: str) -> tuple[Finding, ...]:
    """Контакты в тексте: непересекающиеся, по порядку."""
    text = fold(text)
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
    return prepayment_in_skeleton(skeleton(text))


def prepayment_in_skeleton(words: str) -> bool:
    """То же по готовому скелету (normalize.skeleton): проверка правил считает его один раз.

    Слово с отрицанием не считается: «работаю без предоплаты», «avans nije potreban», «no
    upfront payment». Двойное отрицание — считается: «bez avansa ne dolazim»."""
    for match in _PREPAYMENT.finditer(words):
        before = _window_before(words, match.start())
        after = words[match.end() : match.end() + _WINDOW].split()[:3]
        english = match.group().startswith(_ENGLISH_KEYWORD)
        negated = sum(1 for word in before if word in _NEGATORS or (english and word == "no"))
        if negated % 2 == 1:
            if not any(word in _DOUBLE_NEGATION for word in after):
                continue
        elif _NOT_NEEDED.match(" ".join(after)):
            continue
        return True
    return False


def _window_before(words: str, start: int) -> list[str]:
    """Три слова перед позицией; смотрим не дальше _WINDOW символов, чтобы на тексте из тысяч
    совпадений не делить его целиком для каждого."""
    head = words[max(0, start - _WINDOW) : start]
    tokens = head.split()
    if start > _WINDOW and not head.startswith(" ") and tokens:
        tokens = tokens[1:]  # первое слово окна обрезано
    return tokens[-3:]


def find_domains(text: str, contacts: Sequence[Finding] | None = None) -> tuple[str, ...]:
    """Домены ссылок и адресов почты — для правил модерации по доменам: нижний регистр, без
    www, логина и порта, спрятанные точки раскрыты («bit [.] ly/x», «ｂｉｔ.ｌｙ» → «bit.ly»).
    Ссылки мессенджеров без домена (viber://) не входят. `contacts` — уже найденные в этом
    тексте контакты, чтобы не искать их второй раз."""
    folded = fold(text)
    domains: list[str] = []
    for finding in find_contacts(text) if contacts is None else contacts:
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


def fold(text: str) -> str:
    """Текст для поиска той же длины: символ — его форма NFKC, если она из одного символа
    («０» → «0», «¹» → «1», «ｂ» → «b», «．» → «.»), невидимые и надстрочные знаки — пробел."""
    if text.isascii():
        return text
    return "".join(_fold_char(char) for char in text)


@lru_cache(maxsize=4096)
def _fold_char(char: str) -> str:
    if char.isascii():
        return char
    if unicodedata.category(char) in {"Cf", "Mn", "Me"}:
        return " "
    folded = unicodedata.normalize("NFKC", char)
    if folded in {"。", "｡"}:
        return "."
    return folded if len(folded) == 1 else char


@dataclass(frozen=True, slots=True)
class _Piece:
    digits: str
    start: int
    end: int
    spelled: bool = False
    """Цифра словом или одиночная цифра: после такой части номер идёт и через запятую."""


def _digit_runs(text: str) -> list[Finding]:
    """Телефоны и карты: цифры (и цифры словами), идущие подряд через разделители. Даты и
    время заменяются пробелами той же длины: позиции остальных находок не сдвигаются."""
    text = _TIME.sub(lambda m: " " * len(m.group()), _DATE.sub(_blank_date, text))
    findings: list[Finding] = []
    run: list[_Piece] = []
    tens: _Piece | None = None  # «шестьдесят» ждёт единицу
    previous_end = 0
    for match in _TOKEN.finditer(text):
        piece = _piece(match.group(), match.start(), match.end())
        gap = text[previous_end : match.start()]
        last = tens or (run[-1] if run else None)
        spelled = last is not None and piece is not None and (last.spelled or piece.spelled)
        separator = _SPELLED_SEPARATOR if spelled else _SEPARATOR
        joined = last is not None and separator.fullmatch(gap) is not None
        if piece is None or not joined:
            if tens is not None:
                run.append(_Piece(tens.digits + "0", tens.start, tens.end, spelled=True))
                tens = None
            findings.extend(_classify(text, run))
            run = []
        if piece is None:
            previous_end = match.end()
            continue
        if tens is not None:
            if len(piece.digits) == 1 and _is_unit_word(match.group()):
                run.append(_Piece(tens.digits + piece.digits, tens.start, piece.end, spelled=True))
                tens = None
                previous_end = match.end()
                continue
            run.append(_Piece(tens.digits + "0", tens.start, tens.end, spelled=True))
            tens = None
        if match.group().casefold() in _TENS:
            tens = piece
        else:
            run.append(piece)
        previous_end = match.end()
    if tens is not None:
        run.append(_Piece(tens.digits + "0", tens.start, tens.end, spelled=True))
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
        return _Piece(_UNITS[word], start, end, spelled=True)
    if word in _TENS:
        return _Piece(_TENS[word], start, end, spelled=True)
    if any(char.isdigit() for char in word):
        digits = word.translate(_DIGIT_LOOKALIKES).replace("'", "").replace("’", "")
        if digits and all(char.isdecimal() for char in digits):  # «²» и «⑴» — не цифры номера
            ascii_digits = "".join(str(unicodedata.decimal(c)) for c in digits)
            return _Piece(ascii_digits, start, end, spelled=len(ascii_digits) == 1)
    return None


def _is_unit_word(token: str) -> bool:
    return token.casefold() in _UNITS


def _classify(text: str, run: list[_Piece]) -> list[Finding]:
    """Ряд целиком — карта или телефон; иначе ищем телефон внутри ряда: к номеру приклеилось
    число («Cena 3000 064 123 4567», «064 123 4567 12»)."""
    if not run:
        return []
    digits = "".join(piece.digits for piece in run)
    plus, start = _plus(text, run[0].start)
    card = 13 <= len(digits) <= 19 and not plus and digits[0] in CARD_PREFIXES
    if card and luhn_valid(digits):
        return [Finding(ContactKind.CARD, start, run[-1].end)]
    if _phone(digits, plus=plus):
        return [Finding(ContactKind.PHONE, start, run[-1].end)]
    findings: list[Finding] = []
    first = 0
    while first < len(run):
        plus, start = _plus(text, run[first].start)
        longest: int | None = None
        digits = ""
        for last in range(first, len(run)):
            digits += run[last].digits
            if len(digits) > MAX_PHONE_DIGITS:
                break
            if _phone(digits, plus=plus):
                longest = last
        if longest is None:
            first += 1
            continue
        findings.append(Finding(ContactKind.PHONE, start, run[longest].end))
        first = longest + 1
    return findings


def _plus(text: str, start: int) -> tuple[bool, int]:
    """Стоит ли «+» перед номером (через пробел) и откуда тогда начинается находка."""
    if text[max(0, start - 2) : start].strip().endswith("+"):
        return True, text.rindex("+", 0, start)
    return False, start


def _phone(digits: str, *, plus: bool) -> bool:
    if plus:
        return 8 <= len(digits) <= MAX_PHONE_DIGITS
    if digits.startswith("00"):
        return 10 <= len(digits) <= MAX_PHONE_DIGITS
    if digits.startswith("0"):
        return 8 <= len(digits) <= 11
    if digits[:3] in _COUNTRY_CODES:
        return 11 <= len(digits) <= 12
    # Россия и Казахстан без «+»: 8 999 123-45-67, 7 999 123 45 67 (мобильные и города)
    return len(digits) == 11 and digits[0] in "78" and digits[1] in "3489"
