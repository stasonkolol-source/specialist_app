"""Сербская кириллица → латиница (гаевица), ADR-0013 и ARCHITECTURE §7.4.

Транслитерация однозначна: Љ→Lj, Њ→Nj, Џ→Dž. Обратная — нет (в «injekcija» `nj` — две
буквы), поэтому исходник сербского — кириллица, а латиница генерируется. В словах
заглавными диграф тоже заглавный: ЉУБАВ → LJUBAV, но Љубав → Ljubav.
"""

_LETTERS = str.maketrans(
    "абвгдђежзијклмнопрстћуфхцчшАБВГДЂЕЖЗИЈКЛМНОПРСТЋУФХЦЧШ",
    "abvgdđežzijklmnoprstćufhcčšABVGDĐEŽZIJKLMNOPRSTĆUFHCČŠ",
)
_DIGRAPHS = {"љ": "lj", "њ": "nj", "џ": "dž", "Љ": "Lj", "Њ": "Nj", "Џ": "Dž"}


def sr_cyrl_to_latn(text: str) -> str:
    out: list[str] = []
    for index, char in enumerate(text):
        digraph = _DIGRAPHS.get(char)
        if digraph is None:
            out.append(char)
            continue
        if char.isupper() and _in_caps_word(text, index):
            digraph = digraph.upper()
        out.append(digraph)
    return "".join(out).translate(_LETTERS)


def _in_caps_word(text: str, index: int) -> bool:
    """Соседняя буква заглавная: следующая, а в конце слова — предыдущая."""
    following = text[index + 1] if index + 1 < len(text) else ""
    if following.isalpha():
        return following.isupper()
    previous = text[index - 1] if index > 0 else ""
    return previous.isalpha() and previous.isupper()
