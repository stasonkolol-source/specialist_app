"""ThumbHash совпадает с эталонной JS-реализацией (npm `thumbhash` 0.1.1).

Векторы посчитаны JS-версией на тех же картинках. Байты могут разойтись на единицу в
отдельных коэффициентах (cos в libm и V8 различаются в последнем бите), поэтому сверка —
по полубайтам с допуском 1, а заголовок (средний цвет, пропорции, прозрачность) — точно.
"""

import base64
from collections.abc import Callable

import pytest

from app.modules.media.infrastructure.thumbhash import rgba_to_thumbhash

pytestmark = pytest.mark.unit

Pixel = Callable[[int, int], tuple[int, int, int, int]]


def rgba(w: int, h: int, pixel: Pixel) -> bytes:
    return b"".join(bytes(pixel(x, y)) for y in range(h) for x in range(w))


CASES: dict[str, tuple[int, int, Pixel, str]] = {
    "gradient": (
        32,
        24,
        lambda x, y: ((x * 8) % 256, (y * 10) % 256, ((x + y) * 4) % 256, 255),
        "XRgODZpwd4dxiIiHiHiIh3iACPeI",
    ),
    "strip": (100, 1, lambda x, y: (x * 2, 255 - x * 2, 128, 255), "4IdBAaiIiIiIiAh4d4cPiNc="),
    "pixel": (1, 1, lambda x, y: (10, 200, 30, 255), "VIoon14I9wiIh4hwj3CI+AiIgIAI94cP"),
    "checker": (
        64,
        64,
        lambda x, y: (240, 240, 240, 255) if ((x >> 3) + (y >> 3)) % 2 else (20, 40, 60, 255),
        "o+cBBwCIeHg3KAh3eIiCcYcHeIdwhwgI",
    ),
}


def nibbles(data: bytes) -> list[int]:
    return [n for byte in data for n in (byte & 15, byte >> 4)]


@pytest.mark.parametrize("name", CASES)
def test_matches_the_reference_implementation(name: str) -> None:
    w, h, pixel, expected = CASES[name]
    reference = base64.b64decode(expected)

    got = rgba_to_thumbhash(w, h, rgba(w, h, pixel))

    assert len(got) == len(reference)
    assert got[:5] == reference[:5]  # средний цвет, масштабы, пропорции, прозрачность
    assert all(abs(a - b) <= 1 for a, b in zip(nibbles(got), nibbles(reference), strict=True))


def test_transparency_is_encoded() -> None:
    # канал q здесь постоянный: его коэффициенты — шум, сверяем только заголовок
    reference = base64.b64decode("XiiHKwA3cLh4iHiPSIj3h3h4gIiHeHg=")

    got = rgba_to_thumbhash(20, 30, rgba(20, 30, lambda x, y: (200, 50, (x * 12) % 256, y * 8)))

    assert got[:6] == reference[:6]
    assert got[2] >> 7 == 1  # бит прозрачности


def test_refuses_images_over_100_px() -> None:
    with pytest.raises(ValueError, match="100x100"):
        rgba_to_thumbhash(101, 1, bytes(101 * 4))
