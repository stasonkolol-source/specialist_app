"""Полнота профиля для кабинета S33 (DEVELOPMENT_PLAN 2.10): процент и подсказки, что добавить.

Проверки — с весами: подробное «о себе», районы и прайс весят больше языков. Прайс и описания
позиций — только у «Специалиста»: подработке прайс не обязателен, процент считается без них.
Подсказки — в порядке проверок: кабинет показывает первую. Портфолио добавит 2.11.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from app.modules.specialists.domain.profile import ProfileKind, WorkMode

ABOUT_ENOUGH: Final = 80
"""«О себе» хотя бы в пару предложений: короче — подсказка рассказать подробнее."""


@dataclass(frozen=True, slots=True)
class Hint:
    """Что добавить: `code` — поле или действие, `count` — сколько (позиций без описания)."""

    code: str
    count: int | None = None


@dataclass(frozen=True, slots=True)
class Completeness:
    percent: int
    hints: tuple[Hint, ...]


def completeness(
    *,
    kind: ProfileKind,
    category_ids: Sequence[object],
    headline: str | None,
    about: str | None,
    languages: Sequence[object],
    work_modes: Sequence[WorkMode],
    area_ids: Sequence[object],
    price_items: int,
    undescribed_prices: int,
) -> Completeness:
    """`price_items` — видимые позиции прайса, `undescribed_prices` — из них без описания."""
    travels = WorkMode.AT_CLIENT in work_modes
    checks: list[tuple[int, bool, Hint]] = [
        (15, bool(category_ids), Hint("category_ids")),
        (15, bool(headline), Hint("headline")),
        (20, len((about or "").strip()) >= ABOUT_ENOUGH, Hint("about")),
        (10, bool(languages), Hint("languages")),
        (15, bool(work_modes) and (bool(area_ids) or not travels), Hint("area_ids")),
    ]
    if kind is ProfileKind.PRO:
        checks.append((15, price_items > 0, Hint("services")))
        described = price_items > 0 and undescribed_prices == 0
        checks.append((10, described, Hint("service_descriptions", undescribed_prices)))
    total = sum(weight for weight, _, _ in checks)
    done = sum(weight for weight, ok, _ in checks if ok)
    # без позиций прайса подсказка про их описания ни к чему: сначала — добавить позицию
    hints = tuple(
        hint
        for _, ok, hint in checks
        if not ok and (hint.code != "service_descriptions" or price_items > 0)
    )
    return Completeness(percent=done * 100 // total, hints=hints)
