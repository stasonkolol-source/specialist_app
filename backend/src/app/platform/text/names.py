"""Имена для публичного показа: автор отзыва на карточке специалиста — «Ирина С.» (S08, S11)."""


def short_name(display_name: str) -> str:
    """Имя и первая буква фамилии: «Ana Petrović» → «Ana P.»; одно слово — как есть."""
    first, *rest = display_name.split() or [""]
    if not rest:
        return first
    return f"{first} {rest[-1][0].upper()}."
