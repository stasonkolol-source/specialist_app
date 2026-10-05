"""Текст с клиента перед проверками и записью (QA ADV-03, ADV-04).

- Управляющие символы (Unicode Cc) — прочь, кроме перевода строки и табуляции; CR LF и CR —
  перевод строки. NUL PostgreSQL в тексте не хранит: без очистки — 500 вместо ответа.
- Невидимые символы форматирования (Cf: zero-width space, word joiner, BOM, bidi-override,
  мягкий перенос) и пустые на вид буквы (заполнитель хангыля, пробел Брайля) — прочь везде:
  ими прячут текст и обходят «не пусто» и минимальную длину.
  Оставляем то, без чего ломаются эмодзи: ZWJ и ZWNJ — одиночные между видимыми символами
  (семья, «женщина + ZWJ + гаечный ключ»), селектор варианта — после видимого (красное
  сердце), теги — только во флаге региона (чёрный флаг + теги «gbsct»).
- Обычные пробелы и переводы строк не трогаем: текст из пробелов отклоняет домен своим кодом
  (`invalid_job`, `invalid_message`…), как и раньше. Текст из одних невидимых символов после
  очистки — пустой или из пробелов: его отклоняет `min_length` схемы или тот же домен.

Чистая функция без фреймворков: её подключают схемы HTTP (`platform/http/fields.py`).
"""

import unicodedata
from typing import Final

_KEEP_CONTROLS: Final = frozenset("\n\t")
_JOINERS: Final = frozenset("\u200c\u200d")
"""ZWNJ и ZWJ: соединяют эмодзи и буквы некоторых письменностей."""
_TAG_FLAG: Final = "\U0001f3f4"
"""Чёрный флаг: после него теги U+E0020–E007F кодируют флаг региона."""
_BLANK: Final = frozenset("\u115f\u1160\u3164\uffa0\u2800\u034f")
"""Не Cf, но не видны: пустые буквы хангыля (ими делают «невидимые имена»), пробел Брайля,
соединитель графем."""


def clean_text(text: str) -> str:
    """Текст без управляющих и невидимых символов; пробелы — как были."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    out: list[str] = []
    for index, char in enumerate(text):
        category = unicodedata.category(char)
        if (category == "Cc" and char not in _KEEP_CONTROLS) or char in _BLANK:
            continue
        if (category == "Cf" or _variation_selector(char)) and not _kept(char, out, text, index):
            continue
        out.append(char)
    return "".join(out)


def _kept(char: str, out: list[str], text: str, index: int) -> bool:
    """Нужен ли невидимый символ последовательности: только рядом с тем, что он меняет."""
    before = out[-1] if out else ""
    if char in _JOINERS:
        after = text[index + 1] if index + 1 < len(text) else ""
        return _visible(before) and _visible(after)
    if _tag(char):
        return before == _TAG_FLAG or _tag(before)
    if _variation_selector(char):
        return _visible(before)
    return False


def _visible(char: str) -> bool:
    return (
        bool(char)
        and not char.isspace()
        and char not in _BLANK
        and unicodedata.category(char) not in {"Cc", "Cf"}
        and not _variation_selector(char)
    )


def _tag(char: str) -> bool:
    return "\U000e0020" <= char <= "\U000e007f"


def _variation_selector(char: str) -> bool:
    return (
        "\ufe00" <= char <= "\ufe0f"
        or "\U000e0100" <= char <= "\U000e01ef"
        or "\u180b" <= char <= "\u180d"
        or char == "\u180f"
    )
