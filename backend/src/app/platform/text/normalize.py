"""Скелет текста для поиска слов с обфускацией (ADR-0016 §3, DEVELOPMENT_PLAN 2.4).

Мошенник пишет «пред0плата», «п.р.е.д.о.п.л.а.т.а», «predoplata» или «ПРЕДОПЛАААТА» —
правило должно узнать одно слово. Скелет сводит варианты к одной форме:
- Unicode NFKC и нижний регистр (полноширинные буквы, лигатуры);
- кириллица ru, uk и sr — в латиницу ASCII, латиница без диакритики (č → c, đ → dj);
- «цифры вместо букв» внутри слов: 0 → o, 3 → e, 4 → a, 1 → i, @ → a, $ → s; в слове с
  кириллицей цифры похожи на другие буквы: «3вони» — з, «4ел» — ч, «6ыстро» — б;
- разделители внутри слова из одиночных букв («п.р.е.д»), повторы букв: «аааа», «ss» → «a»,
  «s» — и в тексте, и в словаре, поэтому «massage» и «masssage» сходятся в «masage».

Скелет — только для сравнения, пользователю его не показывают. Слова словаря правил
приводятся тем же `skeleton()`, поэтому сравнение симметрично.
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
_LEET = {"0": "o", "3": "e", "4": "a", "1": "i", "5": "s", "7": "t"}
"""Цифры, которыми заменяют буквы: действуют только внутри слова с буквами."""
_LEET_CYRILLIC = {**_LEET, "3": "z", "4": "c", "6": "b"}
_SIGN = re.compile(r"(?<=[^\W\d_])[@$](?=[^\W\d_])", re.UNICODE)
"""«k@zino», «ca$ino»: знак между буквами — буква, а не граница слова."""
_SIGNS = {"@": "a", "$": "s"}
_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)
_SPACED = re.compile(r"(?<![^\W_])(?:[^\W\d_][\s.·*_\-]){2,}[^\W\d_](?![^\W_])", re.UNICODE)
"""Слово по буквам через разделитель: «п.р.е.д», «p r e d»."""
_REPEATS = re.compile(r"([a-z])\1+")
"""Повтор буквы — одна буква; цифры не трогаем: «1000» остаётся числом."""


def skeleton(text: str) -> str:
    """Скелет для поиска: слова через пробел, без регистра, письменности и маскировки."""
    text = unicodedata.normalize("NFKC", text).casefold()
    text = _SPACED.sub(lambda m: re.sub(r"[\s.·*_\-]", "", m.group()), text)
    text = _SIGN.sub(lambda m: _SIGNS[m.group()], text)
    words = [_word_skeleton(word) for word in _WORD.findall(text)]
    return " ".join(word for word in words if word)


def _word_skeleton(word: str) -> str:
    has_letters = any(char.isalpha() for char in word)
    leet = _LEET_CYRILLIC if any(char in _CYRILLIC for char in word) else _LEET
    out: list[str] = []
    for char in word:
        if char in _CYRILLIC:
            out.append(_CYRILLIC[char])
        elif char in _LATIN:
            out.append(_LATIN[char])
        elif has_letters and char in leet:
            out.append(leet[char])
        elif char.isascii():
            out.append(char)
        else:  # диакритика латиницы: č → c
            base = unicodedata.normalize("NFD", char)[0]
            out.append(base if base.isascii() else "")
    return _REPEATS.sub(r"\1", "".join(out).replace("'", "").replace("’", ""))
