"""Текст пользователя для внешнего AI (ADR-0016: минимум данных и ничего лишнего провайдеру).

- Одиночные суррогаты, управляющие, невидимые (Cf: bidi, «теги» U+E0000…), private-use и
  неназначенные символы удаляются: UTF-8 не всегда может их закодировать (запрос упал бы до
  отправки), а невидимое прячет от модератора «инструкцию» модели. Перевод строки и табуляция
  остаются.
- NFKC: полноширинные и «декоративные» символы — в обычные.
- Контакты маскируются по всему тексту (не длиннее MAX_TEXT, как у правил модерации) и только
  потом текст обрезается: обрезка до маскирования могла бы оставить кусок контакта на границе.
- Длинный текст — начало и конец с «[…]» между ними: мошенничество в хвосте тоже видно.
"""

import unicodedata

from app.platform.text.contact_masking import mask_contacts

MAX_TEXT = 20_000
"""Дальше текст не смотрим: тексты продукта короче, это защита от мусора (как RuleSet)."""
GAP = "\n[…]\n"
_DROP = frozenset({"Cc", "Cf", "Co", "Cs", "Cn"})
_KEEP = frozenset({"\n", "\t"})


def provider_text(text: str, limit: int) -> str:
    """Текст для провайдера: чистый, без контактов, не длиннее `limit`."""
    clean = "".join(
        char for char in text[:MAX_TEXT] if char in _KEEP or unicodedata.category(char) not in _DROP
    )
    masked = mask_contacts(unicodedata.normalize("NFKC", clean))
    if len(masked) <= limit:
        return masked
    tail = limit // 4
    return masked[: limit - tail - len(GAP)] + GAP + masked[-tail:]
