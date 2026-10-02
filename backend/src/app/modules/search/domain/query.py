"""Запрос выдачи специалистов (ARCHITECTURE §9.2–9.5; DEVELOPMENT_PLAN 4.2): чистые правила.

Разбор текста перед FTS (стоп-слова, `đ` → `dj`), веса ранжирования из флага, округление
расстояния и курсор страницы. SQL выдачи — в infrastructure, порядок этапов — в use case.
"""

import base64
import binascii
import json
import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from enum import StrEnum
from typing import Final

from app.modules.search.domain.index import serbian
from app.platform.kernel.pagination import InvalidCursorError

MAX_QUERY: Final = 100
"""Длиннее — не запрос, а текст: обрезаем."""
MAX_OFFSET: Final = 500
"""Глубже выдача не листается (§9.2): релевантность дальше всё равно никто не читает."""
DISTANCE_STEP_M: Final = 500
"""Расстояние в карточке — с точностью до 500 м (§7.6): точный адрес не вычислить."""
DISTANCE_SCALE_M: Final = 3_000
"""d0 затухания по расстоянию (§9.4): exp(−d / d0)."""
TRAVEL_DEFAULT_M: Final = 30_000
"""«Выезжает ко мне», если радиус выезда не задан (§9.5)."""
NEW_UNTIL_REVIEWS: Final = 3
"""Меньше отзывов — «Новый специалист» вместо рейтинга (§9.4)."""
WEIGHTS_FLAG: Final = "search.weights"

SERBIAN_STOPWORDS: Final = frozenset(
    {"i", "u", "za", "na", "od", "do", "sa", "se", "je", "da", "ili", "po", "pri", "kod"}
    | {"и", "у", "за", "на", "од", "до", "са", "се", "је", "да", "или", "по", "при", "код"}
)
"""Сербские стоп-слова (§9.3): у конфигурации serbian своего списка нет — вырезаем сами.
Русские вырезает конфигурация russian."""

BADGE_TRUST: Final = {"phone_verified": 0.3, "id_verified": 0.5, "business_verified": 0.2}
"""Вклад бейджей в доверие (§9.4); бейджи появятся в v1, до того доверие — ноль."""

_WORD = re.compile(r"\w+")


class SpecialistSort(StrEnum):
    RELEVANCE = "relevance"
    RATING = "rating"
    DISTANCE = "distance"
    PRICE = "price"


class Stage(StrEnum):
    """Как найдена выдача (§9.2): страницы дальше берутся тем же этапом."""

    BROWSE = "browse"
    """Без текста — фильтры и порядок."""
    TAXONOMY = "taxonomy"
    """Запрос узнан в словаре категорий целиком или по началу."""
    ALL_WORDS = "all"
    PREFIX = "prefix"
    ANY_WORD = "any"
    """FTS: все слова → по началу слов → любое слово."""
    SIMILAR = "similar"
    """«Возможно, вы имели в виду…»: ближайшее слово словаря."""


FTS_STAGES: Final = (Stage.ALL_WORDS, Stage.PREFIX, Stage.ANY_WORD)


def readable(text: str) -> str:
    """Ввод без управляющих и невидимых символов (категория Unicode C): NUL PostgreSQL не
    примет вовсе, а невидимые знаки ломают словарь и кэш. Вместо них — пробел."""
    return "".join(" " if unicodedata.category(char)[0] == "C" else char for char in text)


@dataclass(frozen=True, slots=True)
class QueryText:
    raw: str
    """Запрос как набран, без лишних пробелов: словарь категорий и поиск по имени."""
    words: tuple[str, ...]
    """Слова для FTS: без стоп-слов, `đ` → `dj`."""

    @classmethod
    def parse(cls, q: str | None) -> QueryText | None:
        raw = " ".join(readable(q or "").split())[:MAX_QUERY].strip()
        words = tuple(
            word for word in _WORD.findall(serbian(raw)) if word.lower() not in SERBIAN_STOPWORDS
        )
        return cls(raw=raw, words=words) if raw and words else None

    def fts(self, stage: Stage) -> str:
        """Текст для platform.q_all / q_prefix_ru_sr: «или» между словами — у websearch."""
        return " or ".join(self.words) if stage is Stage.ANY_WORD else " ".join(self.words)


@dataclass(frozen=True, slots=True, kw_only=True)
class RankWeights:
    """Веса ранжирования §9.4. Без текста запроса его вес не участвует, а остальные
    нормируются на свою сумму — порядок не зависит от того, был ли текст."""

    text: float = 0.35
    rating: float = 0.25
    trust: float = 0.15
    responsiveness: float = 0.10
    """Отзывчивость — с 6.3b; до того сигнала нет, вес на порядок не влияет."""
    activity: float = 0.05
    availability: float = 0.10
    """«Доступен сегодня» — только при «Срочно»: без него вес обнуляет use case."""

    @classmethod
    def from_flag(cls, value: object) -> RankWeights:
        """Веса из флага `search.weights`: известный ключ с числом ≥ 0 заменяет вес по
        умолчанию, остальное игнорируется — опечатка в админке не ломает выдачу."""
        if not isinstance(value, Mapping):
            return cls()
        known = {item.name for item in fields(cls)}
        picked = {
            key: float(number)
            for key, number in value.items()
            if key in known
            and isinstance(number, int | float)
            and not isinstance(number, bool)
            and math.isfinite(number)
            and number >= 0
        }
        return replace(cls(), **picked)


def rounded_distance(meters: float | None) -> int | None:
    """≈ 1,5 км: шаг 500 м, ближе 500 м не показываем."""
    if meters is None:
        return None
    return max(DISTANCE_STEP_M, round(meters / DISTANCE_STEP_M) * DISTANCE_STEP_M)


@dataclass(frozen=True, slots=True)
class PageCursor:
    """Курсор страницы: этап, которым найдена первая страница, и смещение."""

    stage: Stage
    offset: int

    def encode(self) -> str:
        raw = json.dumps([self.stage.value, self.offset], separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @classmethod
    def decode(cls, cursor: str) -> PageCursor:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            stage, offset = json.loads(base64.urlsafe_b64decode(padded.encode()))
            if not isinstance(offset, int) or isinstance(offset, bool):
                raise InvalidCursorError
            if not 0 < offset <= MAX_OFFSET:
                raise InvalidCursorError
            return cls(Stage(stage), offset)
        except (ValueError, TypeError, binascii.Error) as exc:  # json, Stage и распаковка
            raise InvalidCursorError from exc
