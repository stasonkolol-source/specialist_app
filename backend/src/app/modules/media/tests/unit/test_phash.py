"""pHash фото (ADR-0016 L6, DEVELOPMENT_PLAN 7.6): копия — в нескольких битах, другое фото —
далеко; хэш детерминирован и переживает ответ дочернего процесса только в виде 64 бит."""

import io
import json
import random
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.modules.media.application.ports import ProcessingCrashedError
from app.modules.media.domain.asset import DUPLICATE_DISTANCE
from app.modules.media.infrastructure import imaging
from app.modules.media.infrastructure.imaging import process_image
from app.modules.media.infrastructure.phash import BITS, distance, perceptual_hash
from app.modules.media.tests.images import exif

pytestmark = pytest.mark.unit


def scene(seed: int, size: tuple[int, int] = (1600, 1200)) -> Image.Image:
    """Синтетический «снимок»: фон и случайные фигуры — у каждого seed свой."""
    rng = random.Random(seed)  # noqa: S311 — картинка для теста, не секрет
    image = Image.new("RGB", size, (rng.randrange(256), rng.randrange(256), rng.randrange(256)))
    draw = ImageDraw.Draw(image)
    for _ in range(25):
        x, y = rng.randrange(size[0]), rng.randrange(size[1])
        w, h = rng.randrange(50, 600), rng.randrange(50, 600)
        color = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
        draw.ellipse((x, y, x + w, y + h), fill=color)
    return image


def encoded(image: Image.Image, fmt: str = "JPEG", **save: object) -> bytes:
    out = io.BytesIO()
    image.save(out, fmt, **save)
    return out.getvalue()


def reopened(image: Image.Image, **save: object) -> Image.Image:
    return Image.open(io.BytesIO(encoded(image, **save)))


def test_copy_reencoded_resized_or_retouched_stays_within_the_threshold() -> None:
    original = scene(1)
    base = perceptual_hash(original)

    copies = {
        "jpeg q40": reopened(original, quality=40),
        "smaller": original.resize((640, 480)),
        "smaller jpeg": reopened(original.resize((800, 600)), quality=60),
        "brighter": original.point(lambda v: min(255, int(v * 1.1) + 8)),
        "cropped 3%": original.crop((24, 18, 1576, 1182)),
    }

    for name, copy in copies.items():
        assert distance(base, perceptual_hash(copy)) <= DUPLICATE_DISTANCE, name


def test_different_photos_are_far_apart() -> None:
    hashes = [perceptual_hash(scene(seed)) for seed in range(2, 12)]

    distances = [distance(a, b) for i, a in enumerate(hashes) for b in hashes[i + 1 :]]

    assert min(distances) > 2 * DUPLICATE_DISTANCE
    assert 24 <= sum(distances) / len(distances) <= 40  # у случайной пары — около 32


def test_hash_is_deterministic_64_bits_split_at_the_median() -> None:
    first, second = perceptual_hash(scene(7)), perceptual_hash(scene(7))

    assert first == second
    assert 0 <= first < 1 << BITS
    assert first.bit_count() == BITS // 2  # бит — «выше медианы»: ровно половина


def test_distance_counts_differing_bits() -> None:
    assert distance(0, 0) == 0
    assert distance(0b1011, 0b0001) == 2
    assert distance(0, (1 << BITS) - 1) == BITS


def test_processed_photo_carries_its_phash_whatever_the_format_and_orientation() -> None:
    original = scene(3)
    jpeg = process_image(encoded(original, quality=90))
    png = process_image(encoded(original, "PNG"))
    # тот же снимок с камеры: пиксели лежат боком (на 90° против часовой), поворот — в EXIF
    sideways = process_image(encoded(original.rotate(90, expand=True), exif=exif(orientation=6)))

    assert distance(jpeg.phash, png.phash) <= 2
    assert distance(jpeg.phash, sideways.phash) <= 2
    assert distance(jpeg.phash, process_image(encoded(scene(4))).phash) > DUPLICATE_DISTANCE


@pytest.mark.parametrize("phash", ["", "abc", "-" + "f" * 15, "g" * 16, 12345, None])
def test_child_answer_with_a_bad_phash_is_our_failure(tmp_path: Path, phash: object) -> None:
    """Ответ процесса недоверенный: хэш — ровно 16 шестнадцатеричных знаков, иначе повтор."""
    (tmp_path / imaging.ANSWER).write_text(
        json.dumps(
            {
                "ok": True,
                "width": 1,
                "height": 1,
                "placeholder": "x",
                "sha256": "00" * 32,
                "phash": phash,
                "variants": [],
            }
        )
    )

    with pytest.raises(ProcessingCrashedError):
        imaging._result(tmp_path)
