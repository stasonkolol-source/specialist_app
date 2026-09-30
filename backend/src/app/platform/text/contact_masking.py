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
- счета сербских банков: 3-13-2 цифры с контрольным числом по модулю 97;
- ссылки: http(s), www, домены с распространёнными зонами, t.me, wa.me, viber — и точки,
  спрятанные как «[.]», «(.)», «[dot]», « dot », « точка »;
- e-mail (в том числе «(at)», « собака »), @username Telegram (и «tg @ ivan» после названия
  мессенджера).
Предоплату (`find_prepayment`) не маскируют: это сигнал для правил, а не контакт.

Даты («12.10.2026»), время в диапазонах и после предлогов («08.00-16.00», «с 9:00»), цены
(«1 000 000 RSD», «1000, 1200, 1800 din», «2000 2500 3000 3500»), размеры («0 60 120 180»)
телефоном, картой и счётом не считаются. «posao.To je sve» и «posao.to je sve» — не ссылки:
зона домена пишется строчными (или весь адрес — прописными), а зоны, которые совпадают с
обычными словами (.to, .si, .de, .me …), считаются ссылкой только с путём («majstor.me/x»).
«I'm @ home» — не @username.

Позиции находок — в исходном тексте. Поиск идёт по свёрнутому тексту: невидимые символы и
надстрочные знаки удалены, буква с разложенной диакритикой собрана, каждый символ — в форме
NFKC («０» → «0», «¹» → «1», «ｂ» → «b»); карта индексов переводит находку обратно. Время —
линейное от длины текста: регулярные выражения начинают совпадение только в начале цепочки
и не перебирают её заново.
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

from app.platform.text.normalize import clauses


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
ACCOUNT_DIGITS = 18
"""Счёт сербского банка: банк (3), номер (13, с нулями впереди), контрольное число (2)."""
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
    "rs", "срб", "com", "net", "org", "ru", "рф", "ua", "info", "biz", "eu", "ba", "hr", "mk",
    "xyz",
)  # fmt: skip
"""Зоны, которые не спутать с обычным словом."""
_WORD_TLDS = (
    "me", "io", "app", "si", "de", "at", "ch", "uk", "us", "co", "site", "online", "shop",
    "store", "link", "ly", "gl", "gg", "to", "tv", "top", "pro", "club", "live", "page", "dev",
)  # fmt: skip
"""Зоны-слова и частые сокращения («sam.si li tu», «posao.to je sve»): ссылка — только с путём."""
_TLD = "(?-i:" + "|".join(_TLDS) + ")"
_WORD_TLD = "(?-i:" + "|".join(_WORD_TLDS) + ")"
_TLD_UPPER = "(?-i:" + "|".join(tld.upper() for tld in (*_TLDS, *_WORD_TLDS) if tld.isascii()) + ")"
_ANY_TLD = f"(?:{_TLD}|{_WORD_TLD})"
_LABEL = r"[\w\-]++"
_LABELS = 8
"""Частей домена до зоны — не больше 8 (a.b.majstor.co.rs — четыре): иначе на «x[.]x[.]…»
каждое совпадение перебирало бы всю цепочку (квадратичное время)."""
_START = r"(?<![\w\-.])"
"""Совпадение начинается только в начале цепочки «слово-слово.слово»: без этого поиск на
«a-a-a-…» перебирал бы цепочку с каждой буквы (квадратичное время)."""
_HOST = rf"{_START}{_LABEL}(?:{_DOT}{_LABEL}){{0,{_LABELS}}}{_DOT}"
_LINK = re.compile(
    rf"https?://\S+|www{_DOT}\S+|\b(?:t|wa|telegram)(?:\s*\.\s*|{_HIDDEN_DOT})me\s*/\s*[\w+]+"
    rf"|viber://\S+"
    rf"|{_HOST}{_TLD}(?![\w\-])(?:/\S*)?"
    rf"|{_HOST}{_WORD_TLD}/\S+"
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
    rf"|{_AT_WORD}{_LABEL}(?:{_DOT}{_LABEL}){{0,{_LABELS}}}{_DOT}{_ANY_TLD})(?![\w\-])",
    re.IGNORECASE | re.UNICODE,
)
"""Адрес со словом вместо «@» («ivan собака mail точка ru») — только с известной зоной:
«Есть собака лабрадор.Нужен выгул» — не почта."""
_USERNAME = re.compile(r"(?<![\w.])@[A-Za-z][A-Za-z0-9_]{3,31}\b")
_MESSENGER_USERNAME = re.compile(
    r"(?i:\b(?:tg|telegram|телеграм\w*|телег\w*|тг|viber|вайбер\w*|insta\w*|инст\w*|whatsapp"
    r"|ватсап\w*|вотсап\w*))\W{0,3}?(@\s+[A-Za-z][A-Za-z0-9_]{3,31})\b"
)
"""«tg @ ivan_master»: после названия мессенджера «@» с пробелом — тоже @username."""
_DATE = re.compile(
    r"\b(\d{1,2})([./])(\d{1,2})\2(?:\d{4}|\d{2})\b"
    r"|\b(\d{1,2})-(\d{1,2})-\d{4}\b"
    r"|\b(\d{1,2})\.(\d{1,2})\.(?!\d)"
)
"""Даты «01.10.2026», «01/10/26», «01-10-2026», «1.10.» — не телефон, даже с нулём впереди.
Дефис — только с годом из четырёх цифр: «123-45-67» — это телефон."""
_CLOCK = r"(?:[01]?\d|2[0-3])[.:][0-5]\d"
_TIME_RANGE = re.compile(rf"(?<![\d.:]){_CLOCK}\s*[-–—]\s*{_CLOCK}(?![\d.:])")
_TIME_AFTER = re.compile(
    rf"\b(?:od|do|с|до|в|u|at|from|to|until|posle|после|nakon|oko|около|around|after|before"
    rf"|pre|перед)\s+({_CLOCK})(?![\d.:])",
    re.IGNORECASE,
)
_TIME_UNIT = re.compile(
    rf"(?<![\d.:])({_CLOCK})(?=\s*(?:h|ч|часов|časova|casova|sati|сати)\b)", re.IGNORECASE
)
"""Время — в диапазоне («08.00-16.00», «01.10-05.10»), после предлога («с 9:00», «od 07.30»)
или с «ч»/«h». Отдельно стоящее «12:34» может быть частью номера («064 123 12:34»)."""

_PRONOUN = r"(?:(?:mne|nam|mi|meni|nama|me|us|to|ti|vam|vama|tebe)\s+)?"
"""«Переведите мне на карту», «уплатите нам унапред»: местоимение между глаголом и целью."""
_PREPAYMENT = re.compile(
    r"\b(?:"
    # ru / uk / sr: предоплата, аванс, залог, завдаток, капара, «оплата заранее»,
    # «переведите на карту»
    r"pred?oplat\w*|peredoplat\w*|avans\w*|zalog(?:a|u|om|e)?\b(?! uspeh)"
    r"|zavdat(?:ok|ku|kom|ka)|kapar(?:a|e|u|om)|depozit\w*|predujam\w*"
    rf"|(?:oplat|uplat|plat|plac)\w*\s+{_PRONOUN}(?:zarane|vpered|unapred|unaprijed)"
    r"|(?:zarane|vpered|unapred|unaprijed)\s+(?:oplat|uplat|plat|plac)\w*"
    rf"|(?:perevedi\w*|skin\w*|kin(?:te|i|u)?)\s+{_PRONOUN}(?:na\s+)?(?:kart|sc[eo]t)\w*"
    # en
    r"|prepay\w*|pre\s?pay\w*|upfront|advance\s+payment|pay\s+(?:in\s+)?advance|deposit\w*"
    r")\b"
)
"""По скелету фразы (normalize.clauses): «предоплата», «predoplata» и «пред0плата» — одно
слово. В скелете нет двойных букв: «заранее» — это «zarane». Основы узкие: «zalogaj»,
«kaparima», «завдати шкоди», «kino karte» — не предоплата."""
_ENGLISH_KEYWORD = ("prepay", "pre pay", "upfront", "advance", "pay", "deposit")
_NEGATORS = frozenset(
    {"bez", "ne", "ni", "net", "nema", "nije", "nisu", "nikada", "nikad", "nikogda", "not",
     "without", "never", "dont", "doesnt", "wont", "nikakoj", "nikakuju", "nikakih",
     "nikakogo", "nikakav", "nikakvu", "nikakve", "nikakvog", "nikakva", "nikakvi"}
)  # fmt: skip
"""Отрицание, которое прямо относится к слову: «без предоплаты», «bez avansa», «никакой
предоплаты», «without deposit». Английское «no» — только перед английским словом: русское
«но» в скелете — тоже «no»."""
_NEGATED_VERBS = frozenset(
    {"beru", "berem", "beremo", "uzimam", "uzimamo", "trazim", "trazimo", "trebam", "treba",
     "trebuju", "trebuem", "trebuetsja", "nado", "nuzna", "nuzno", "nuzen", "nuzny", "potreban",
     "potrebna", "potrebno", "potrebni", "prosu", "prosim", "take", "need", "require", "ask",
     "charge", "want", "accept", "primam", "primamo"}
)  # fmt: skip
"""Глагол между отрицанием и словом: «не беру аванс», «ne treba avans», «don't take»."""
_DETERMINERS = frozenset({"any", "a", "an", "the", "nikakuju", "nikakoj", "nikakvu", "nikakav"})
_NOT_NEEDED = re.compile(
    r"(?:je\s+|is\s+)?(?:ne|nije|nisu|not|isnt)\s+(?:nuzn|nuzen|treb|potreb|neophod|obavez"
    r"|objazat|required|needed|necessary)"
)
"""Отрицание сразу после слова: «предоплата не нужна», «avans nije potreban», «prepayment is
not required»."""
_DOUBLE_NEGATION = frozenset(
    {"ne", "nece", "necu", "necemo", "not", "wont", "dont", "nisam", "nikak", "nikako"}
)
"""Требование: «bez avansa ne dolazim», «без предоплаты никак», «…мы не выезжаем»."""

_HIDDEN_DOT_RE = re.compile(_HIDDEN_DOT, re.IGNORECASE)
_SPACED_DOT = re.compile(r"\s*\.\s*")
_AT_RE = re.compile(_AT, re.IGNORECASE)
_SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.IGNORECASE)
_AUTHORITY_END = re.compile(r"[/?#\s]")
_MARKS = frozenset({"Mn", "Me"})


@dataclass(frozen=True, slots=True)
class ContactScan:
    findings: tuple[Finding, ...]
    domains: tuple[str, ...]


def scan_contacts(text: str) -> ContactScan:
    """Контакты и их домены за один проход — для правил модерации."""
    folded = _fold(text)
    found = _find_folded(folded.text)
    return ContactScan(
        findings=tuple(Finding(f.kind, *folded.span(f.start, f.end)) for f in found),
        domains=_domains(folded.text, found),
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
    return any(_asks_in_clause(words) for words in clauses(text))


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
    """Текст для поиска: буква с надстрочными знаками — одна буква, невидимые символы и
    знаки — удалены, каждый символ — в форме NFKC, «。» — точка."""
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


@lru_cache(maxsize=4096)
def _fold_cluster(cluster: str) -> str:
    if unicodedata.category(cluster[0]) in {"Cf", "Mn", "Me"}:
        return ""
    folded = unicodedata.normalize("NFKC", cluster)
    folded = "".join(char for char in folded if unicodedata.category(char) not in _MARKS)
    return folded.replace("。", ".").replace("｡", ".")


def _find_folded(text: str) -> list[Finding]:
    found = [
        *_digit_runs(text),
        *(Finding(ContactKind.EMAIL, m.start(), m.end()) for m in _EMAIL.finditer(text)),
        *(Finding(ContactKind.LINK, m.start(), m.end()) for m in _LINK.finditer(text)),
        *(Finding(ContactKind.USERNAME, m.start(), m.end()) for m in _USERNAME.finditer(text)),
        *(
            Finding(ContactKind.USERNAME, m.start(1), m.end(1))
            for m in _MESSENGER_USERNAME.finditer(text)
        ),
    ]
    found.sort(key=lambda f: (f.start, -(f.end - f.start)))
    result: list[Finding] = []
    for finding in found:
        if result and finding.start < result[-1].end:  # вложенное или пересекающееся
            continue
        result.append(finding)
    return result


# --- предоплата --------------------------------------------------------------------------------


def _asks_in_clause(words: str) -> bool:
    tokens = words.split()
    index = 0  # номер слова, с которого начинается совпадение
    scanned = 0
    for match in _PREPAYMENT.finditer(words):
        index += words.count(" ", scanned, match.start())
        scanned = match.start()
        first, last = index, index + match.group().count(" ")
        english = match.group().startswith(_ENGLISH_KEYWORD)
        if not _negated(tokens, first, last, english=english):
            return True
    return False


def _negated(tokens: Sequence[str], first: int, last: int, *, english: bool) -> bool:
    before = list(reversed(tokens[max(0, first - 3) : first]))  # ближнее слово — первое

    def negator(word: str) -> bool:
        return word in _NEGATORS or (english and word == "no")

    direct = bool(before) and (
        negator(before[0])
        or (len(before) >= 2 and before[0] in _NEGATED_VERBS and negator(before[1]))
        or (
            len(before) >= 3
            and before[0] in _DETERMINERS
            and before[1] in _NEGATED_VERBS
            and negator(before[2])
        )
    )
    after = tokens[last + 1 :]
    if direct:
        return not _double_negation(after)
    return _NOT_NEEDED.match(" ".join(after[:4])) is not None or after in (["net"], ["nema"])


def _double_negation(after: Sequence[str]) -> bool:
    """«Ne» дальше во фразе, если оно не отрицает следующее слово-предоплату («без
    предоплаты и не беру аванс» — не двойное)."""
    for position, word in enumerate(after):
        if word in _DOUBLE_NEGATION:
            ahead = " ".join(after[position + 1 : position + 4])
            if not _PREPAYMENT.search(ahead):
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


def _digit_runs(text: str) -> list[Finding]:
    """Телефоны, карты и счета: цифры (и цифры словами), идущие подряд через разделители. Даты
    и время заменяются пробелами той же длины: позиции остальных находок не сдвигаются."""
    text = _blank_times(_DATE.sub(_blank_date, text))
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
                run.append(_Piece(tens.digits + "0", tens.start, tens.end, spelled=True, word=True))
                tens = None
            findings.extend(_classify(text, run))
            run = []
        if piece is None:
            previous_end = match.end()
            continue
        if tens is not None:
            if len(piece.digits) == 1 and _is_unit_word(match.group()):
                run.append(
                    _Piece(
                        tens.digits + piece.digits, tens.start, piece.end, spelled=True, word=True
                    )
                )
                tens = None
                previous_end = match.end()
                continue
            run.append(_Piece(tens.digits + "0", tens.start, tens.end, spelled=True, word=True))
            tens = None
        if match.group().casefold() in _TENS:
            tens = piece
        else:
            run.append(piece)
        previous_end = match.end()
    if tens is not None:
        run.append(_Piece(tens.digits + "0", tens.start, tens.end, spelled=True, word=True))
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


def _blank_times(text: str) -> str:
    text = _TIME_RANGE.sub(lambda m: " " * len(m.group()), text)
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
    if word in _TENS:
        return _Piece(_TENS[word], start, end, spelled=True, word=True)
    if any(char.isdigit() for char in word):
        digits = word.translate(_DIGIT_LOOKALIKES).replace("'", "").replace("’", "")
        if digits and all(char.isdecimal() for char in digits):  # «²» и «⑴» — не цифры номера
            ascii_digits = "".join(str(unicodedata.decimal(c)) for c in digits)
            return _Piece(ascii_digits, start, end, spelled=len(ascii_digits) == 1)
    return None


def _is_unit_word(token: str) -> bool:
    return token.casefold() in _UNITS


def _classify(text: str, run: list[_Piece]) -> list[Finding]:
    """Ряд целиком — счёт, карта или телефон; иначе ищем телефон внутри ряда: к номеру
    приклеилось число («Cena 3000 064 123 4567», «064 123 4567 12»)."""
    if not run:
        return []
    digits = "".join(piece.digits for piece in run)
    plus, start = _plus(text, run[0].start)
    if not plus and account_valid(digits):
        return [Finding(ContactKind.ACCOUNT, start, run[-1].end)]
    if not plus and _card(digits, run):
        return [Finding(ContactKind.CARD, start, run[-1].end)]
    if _phone(digits, run, plus=plus):
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
            if not digits.startswith("00") and _phone(digits, run[first : last + 1], plus=plus):
                longest = last  # «00…» внутри ряда — скорее номер счёта, чем телефон
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


def _card(digits: str, run: list[_Piece]) -> bool:
    if not 13 <= len(digits) <= 19 or digits[0] not in CARD_PREFIXES:
        return False
    if len(run) >= 3 and all(piece.digits.endswith("0") for piece in run):
        return False  # «2000 2500 3000 3500» — прайс, а не карта
    return luhn_valid(digits)


def _phone(digits: str, run: Sequence[_Piece], *, plus: bool) -> bool:
    if plus:
        return 8 <= len(digits) <= MAX_PHONE_DIGITS
    if digits.startswith("00"):
        return 10 <= len(digits) <= MAX_PHONE_DIGITS
    if digits.startswith("0"):
        # «0 60 120 180» — размеры: номер не начинается одиночным нулём перед числом
        lone_zero = (
            run[0].digits == "0" and not run[0].word and len(run) > 1 and len(run[1].digits) > 1
        )
        return 9 <= len(digits) <= 11 and not lone_zero
    if digits[:3] in _COUNTRY_CODES:
        return 11 <= len(digits) <= 12
    # Россия и Казахстан без «+»: 8 999 123-45-67, 7 999 123 45 67 (мобильные и города)
    return len(digits) == 11 and digits[0] in "78" and digits[1] in "3489"
