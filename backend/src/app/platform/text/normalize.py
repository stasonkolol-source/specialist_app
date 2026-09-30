"""Скелет текста для поиска слов с обфускацией (ADR-0016 §3, DEVELOPMENT_PLAN 2.4).

Мошенник пишет «пред0плата», «п.р.е.д.о.п.л.а.т.а», «predoplata», «ПРЕДОПЛАААТА» или прячет
в слово невидимый символ — правило должно узнать одно слово. Скелет сводит варианты к одной
форме:
- Unicode NFKC и нижний регистр (полноширинные буквы, лигатуры); невидимые символы (Cf:
  zero-width, мягкий перенос) и надстрочные знаки (ударение «закладчи́к») убираются;
- кириллица ru, uk и sr — в латиницу ASCII, латиница без диакритики (č → c, đ → dj), буквы-
  двойники других письменностей (греческая «ο», кириллическая «ѕ») — в латинские;
- русский транслит латиницей: «ch», «sh», «zh», «kh», «shch», «ya», «yu» — как в скелете
  кириллицы («zakladchik» = «закладчик»);
- «цифры вместо букв» внутри слов: 0 → o, 3 → e, 4 → a, 1 → i, @ → a, $ → s; в слове с
  кириллицей цифры похожи на другие буквы: «3вони» — з, «4ел» — ч, «6ыстро» — б. Число
  остаётся числом: «3000р», «50e», «100к» — не буквы;
- слово по буквам через разделители («п.р.е.д», «p. r. e. d», «п/р/е/д»), повторы букв:
  «аааа», «ss» → «a», «s» — и в тексте, и в словаре, поэтому «massage» и «masssage» сходятся
  в «masage».

Скелет — только для сравнения, пользователю его не показывают. Слова словаря правил
приводятся тем же `skeleton()`, поэтому сравнение симметрично. Время — линейное от длины
текста: регулярные выражения без вложенного перебора.
"""

import re
import unicodedata

_CYRILLIC = {
    "а": "a", "б": "b", "в": "v", "г": "g", "ґ": "g", "д": "d", "ђ": "dj", "е": "e",
    "ё": "e", "є": "e", "ж": "z", "з": "z", "и": "i", "і": "i", "ї": "i", "й": "j",
    "ј": "j", "к": "k", "л": "l", "љ": "lj", "м": "m", "н": "n", "њ": "nj", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "ћ": "c", "у": "u", "ф": "f", "х": "h",
    "ц": "c", "ч": "c", "џ": "dz", "ш": "s", "щ": "s", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "ju", "я": "ja",
}  # fmt: skip
"""Упрощённый транслит: «чш» и «шщ» сливаются — важна узнаваемость, а не обратимость."""
_LATIN = {"đ": "dj", "ß": "ss", "æ": "ae", "ø": "o", "ł": "l"}
_CONFUSABLE = {
    # греческие двойники латиницы
    "α": "a", "β": "b", "γ": "y", "ε": "e", "η": "n", "ι": "i", "κ": "k", "μ": "m",
    "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "υ": "u", "χ": "x", "ω": "w", "ς": "s",
    # кириллица вне ru, uk, sr, похожая на латиницу
    "ѕ": "s", "һ": "h", "ԁ": "d", "ӏ": "l", "ԛ": "q", "ԝ": "w", "ү": "y", "ҽ": "e",
    # латинские двойники
    "ı": "i", "ɑ": "a", "ɡ": "g", "ⅰ": "i",
}  # fmt: skip
"""Буквы, которые выглядят как латиница: без таблицы «kοkain» с греческой «ο» потерял бы букву."""
_LEET = {"0": "o", "3": "e", "4": "a", "1": "i", "5": "s", "7": "t"}
_LEET_CYRILLIC = {**_LEET, "3": "z", "4": "c", "6": "b"}
_DIGRAPHS = re.compile(r"shch|ch|sh|zh|kh|ya|yu")
_DIGRAPH = {"shch": "s", "ch": "c", "sh": "s", "zh": "z", "kh": "h", "ya": "ja", "yu": "ju"}
_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)
_LETTER = r"[^\W\d_]"
_GAP = r"(?:[.·*_\-/|]\s?|\s)"
"""Между буквами слова по буквам: знак (и, может быть, пробел после него) или пробел."""
_GAP_CHAR = r"[.·*_\-/|\s]"
_SPACED = re.compile(
    rf"(?<![^\W_])"
    rf"(?<!\W{_LETTER}{_GAP_CHAR})(?<!^{_LETTER}{_GAP_CHAR})"
    rf"(?<!\W{_LETTER}[.·*_\-/|]\s)(?<!^{_LETTER}[.·*_\-/|]\s)"
    rf"(?:{_LETTER}{_GAP}){{2,}}{_LETTER}(?![^\W_])",
    re.UNICODE,
)
"""Слово по буквам: «п.р.е.д», «p r e d», «p. r. e. d», «п/р/е/д». Просмотр назад не даёт
начать внутри такой цепочки (перед буквой — одиночная буква и разделитель), поэтому поиск
линейный и на «a-a-a-…» длиной в 20 000 символов."""
_SIGN = re.compile(r"(?<=[^\W\d_])[@$](?=[^\W\d_])", re.UNICODE)
"""«k@zino», «ca$ino»: знак между буквами — буква, а не граница слова."""
_SIGNS = {"@": "a", "$": "s"}
_DIGITS = re.compile(r"\d+")
_REPEATS = re.compile(r"([a-z])\1+")
"""Повтор буквы — одна буква; цифры не трогаем: «1000» остаётся числом."""


def skeleton(text: str) -> str:
    """Скелет для поиска: слова через пробел, без регистра, письменности и маскировки."""
    text = unicodedata.normalize("NFKC", text).casefold()
    text = "".join(char for char in text if unicodedata.category(char) not in {"Cf", "Mn"})
    text = _SPACED.sub(lambda m: re.sub(r"[\s.·*_\-/|]", "", m.group()), text)
    text = _SIGN.sub(lambda m: _SIGNS[m.group()], text)
    words = [_word_skeleton(word) for word in _WORD.findall(text)]
    return " ".join(word for word in words if word)


def _word_skeleton(word: str) -> str:
    letters = sum(1 for char in word if char.isalpha())
    leet = _LEET_CYRILLIC if any(char in _CYRILLIC for char in word) else _LEET
    if letters:
        word = _DIGITS.sub(lambda m: _leet(m, word, letters, leet), word)
    out: list[str] = []
    for char in word:
        if char in _CYRILLIC:
            out.append(_CYRILLIC[char])
        elif char in _LATIN:
            out.append(_LATIN[char])
        elif char in _CONFUSABLE:
            out.append(_CONFUSABLE[char])
        elif char.isascii():
            out.append(char)
        else:  # диакритика латиницы: č → c
            base = unicodedata.normalize("NFD", char)[0]
            out.append(base if base.isascii() else "")
    latin = "".join(out).replace("'", "").replace("’", "")
    return _REPEATS.sub(r"\1", _DIGRAPHS.sub(lambda m: _DIGRAPH[m.group()], latin))


def _leet(match: re.Match[str], word: str, letters: int, leet: dict[str, str]) -> str:
    """Цифры в слове — буквы, только если их мало и они стоят среди букв: одна цифра у края
    слова из двух и больше букв («3вони») или одна-две между буквами («g00gle»)."""
    digits = match.group()
    inside = match.start() > 0 and match.end() < len(word)
    if (len(digits) <= 2 and inside) or (len(digits) == 1 and letters >= 2):
        return "".join(leet.get(digit, digit) for digit in digits)
    return digits
