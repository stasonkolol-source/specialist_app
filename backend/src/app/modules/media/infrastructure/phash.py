"""Перцептивный хэш фото — pHash (ARCHITECTURE §10.3 «Антифрод», ADR-0007, ADR-0016 L6).

64 бита DCT, как у pHash.org: кадр в оттенках серого уменьшается до 32 × 32 усреднением,
из двумерного DCT-II берутся частоты 1–8 по обеим осям (без постоянной составляющей: яркость
на хэш не влияет), бит — коэффициент больше медианы этих 64. Пересжатое, уменьшенное или чуть
подправленное фото даёт хэш в нескольких битах от исходного, другое фото — около 32 бит (у
случайной пары расстояние Хэмминга — биномиальное, 32 ± 4).

Чистый Python без numpy: нужен только блок 8 × 8 низких частот, а DCT разделим — сначала по
строкам, потом по столбцам; косинусы — таблицей при импорте. На кадр — около 10 тысяч
умножений, доли миллисекунды рядом с декодированием. Порядок сложений фиксирован, поэтому хэш
детерминирован.
"""

import math
from statistics import median
from typing import Final

from PIL import Image

SIDE: Final = 32
"""Кадр перед DCT: 32 × 32 — мелкие детали и шум сжатия усредняются."""
BLOCK: Final = 8
"""Низкие частоты 1–8 по каждой оси: 64 коэффициента — 64 бита."""
BITS: Final = BLOCK * BLOCK

_COSINES: Final = tuple(
    tuple(math.cos((2 * x + 1) * u * math.pi / (2 * SIDE)) for x in range(SIDE))
    for u in range(1, BLOCK + 1)
)
"""cos((2x + 1)uπ / 2N) для частот u = 1…8: множители нормировки DCT одинаковы у всех
взятых частот и на сравнение с медианой не влияют — их нет."""


def perceptual_hash(image: Image.Image) -> int:
    """pHash кадра — 64-битное число без знака (старший бит — частота (1, 1))."""
    gray = image.convert("L").resize((SIDE, SIDE), Image.Resampling.BOX)
    pixels = gray.tobytes()
    rows = [pixels[y * SIDE : (y + 1) * SIDE] for y in range(SIDE)]
    by_rows = [[_dot(cosine, row) for cosine in _COSINES] for row in rows]
    coefficients = [
        _dot(cosine, [row[u] for row in by_rows]) for cosine in _COSINES for u in range(BLOCK)
    ]
    middle = median(coefficients)
    value = 0
    for coefficient in coefficients:
        value = (value << 1) | (coefficient > middle)
    return value


def distance(a: int, b: int) -> int:
    """Расстояние Хэмминга: сколько бит различаются (в БД то же — `bit_count(a # b)`)."""
    return (a ^ b).bit_count()


def _dot(cosine: tuple[float, ...], values: bytes | list[float]) -> float:
    return math.fsum(c * v for c, v in zip(cosine, values, strict=True))
