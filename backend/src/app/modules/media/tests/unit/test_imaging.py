"""Обработка фото (ARCHITECTURE §10.3): варианты без EXIF и GPS, HEIC, бомбы, мусор.

«Готово, когда» шага 2.2: HEIC с GPS → WebP без EXIF и GPS; decompression bomb — отказ.
"""

import io

import pillow_heif
import pytest
from PIL import ExifTags, Image, ImageCms

from app.modules.media.application.ports import UnprocessableMediaError
from app.modules.media.domain.asset import FailureReason
from app.modules.media.infrastructure import imaging
from app.modules.media.infrastructure.imaging import MAX_PIXELS, process_image
from app.modules.media.tests.images import exif, photo, png_header_only

pytestmark = pytest.mark.unit


def assert_clean(body: bytes) -> Image.Image:
    """WebP без метаданных: ни EXIF (с GPS), ни XMP, ни ICC."""
    variant = Image.open(io.BytesIO(body))
    assert variant.format == "WEBP"
    assert not variant.getexif()
    assert not {"exif", "xmp", "icc_profile"} & variant.info.keys()
    return variant


def test_jpeg_with_gps_becomes_three_clean_webp_variants() -> None:
    result = process_image(photo("JPEG", exif=exif()))

    assert [(v.name, v.width, v.height) for v in result.variants] == [
        ("thumb", 320, 240),
        ("md", 800, 600),
        ("lg", 1600, 1200),
    ]
    for variant in result.variants:
        assert_clean(variant.body)
    assert (result.width, result.height) == (1600, 1200)  # размеры самого крупного варианта
    assert len(result.sha256) == 32
    assert 20 <= len(result.placeholder) <= 40  # ThumbHash в base64


def test_heic_with_gps_loses_exif_and_gps() -> None:
    pillow_heif.register_heif_opener()
    heic = photo("HEIF", exif=exif().tobytes(), quality=70)
    assert Image.open(io.BytesIO(heic)).getexif().get_ifd(ExifTags.IFD.GPSInfo)  # GPS был

    result = process_image(heic)

    assert [v.name for v in result.variants] == ["thumb", "md", "lg"]
    for variant in result.variants:
        assert_clean(variant.body)


def test_orientation_from_exif_is_applied() -> None:
    # 6 — снято «на боку»: показывать надо повёрнутым на 90°
    result = process_image(photo("JPEG", exif=exif(orientation=6)))

    assert (result.width, result.height) == (1200, 1600)
    assert (result.variants[0].width, result.variants[0].height) == (240, 320)


def test_color_profile_is_applied_and_dropped() -> None:
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()

    result = process_image(photo("JPEG", icc_profile=srgb))

    assert_clean(result.variants[-1].body)


def test_transparency_survives() -> None:
    image = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    image.paste((255, 0, 0, 255), (100, 100, 300, 300))
    out = io.BytesIO()
    image.save(out, "PNG")

    result = process_image(out.getvalue())

    thumb = assert_clean(result.variants[0].body)
    assert thumb.mode == "RGBA"
    corner = thumb.getpixel((0, 0))
    assert isinstance(corner, tuple)
    assert corner[3] == 0


def test_small_photo_is_not_upscaled() -> None:
    result = process_image(photo("PNG", size=(640, 480)))

    assert [(v.name, v.width, v.height) for v in result.variants] == [
        ("thumb", 320, 240),
        ("md", 640, 480),
    ]


@pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
def test_decompression_bomb_is_refused_before_decoding() -> None:
    side = int(MAX_PIXELS**0.5) + 100

    with pytest.raises(UnprocessableMediaError) as caught:
        process_image(png_header_only(side, side))

    assert caught.value.reason is FailureReason.TOO_MANY_PIXELS


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n", FailureReason.UNSUPPORTED),
        (b"GIF89a" + bytes(64), FailureReason.UNSUPPORTED),
        (photo("JPEG")[:2000], FailureReason.UNREADABLE),
    ],
    ids=["pdf", "gif-not-allowed", "truncated-jpeg"],
)
def test_files_that_are_not_allowed_photos_are_refused(data: bytes, reason: FailureReason) -> None:
    with pytest.raises(UnprocessableMediaError) as caught:
        process_image(data)

    assert caught.value.reason is reason


def heif_frames(*sizes: tuple[int, int], primary: int) -> bytes:
    """HEIF с несколькими изображениями; основное — `primary`."""
    pillow_heif.register_heif_opener()
    frames = [Image.new("RGB", size, (90, 140, 200)) for size in sizes]
    heif = pillow_heif.from_pillow(frames[0])
    for frame in frames[1:]:
        heif.add_from_pillow(frame)
    out = io.BytesIO()
    heif.save(out, quality=60, primary_index=primary)
    return out.getvalue()


def test_heif_uses_its_primary_image_not_the_first_one(monkeypatch: pytest.MonkeyPatch) -> None:
    # бомба пряталась в кадре №0 за маленьким основным изображением
    monkeypatch.setattr(imaging, "MAX_PIXELS", 10_000)

    result = process_image(heif_frames((400, 300), (40, 30), primary=1))

    assert [(v.width, v.height) for v in result.variants] == [(40, 30)]


def test_heif_with_a_huge_primary_image_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(imaging, "MAX_PIXELS", 10_000)

    with pytest.raises(UnprocessableMediaError) as caught:
        process_image(heif_frames((40, 30), (400, 300), primary=1))

    assert caught.value.reason is FailureReason.TOO_MANY_PIXELS


def test_broken_color_profile_keeps_the_photo() -> None:
    result = process_image(photo("JPEG", icc_profile=b"not an icc profile at all"))

    assert_clean(result.variants[-1].body)


def test_sixteen_bit_grey_keeps_its_tone() -> None:
    out = io.BytesIO()
    Image.new("I;16", (64, 64), 30_000).save(out, "PNG")

    thumb = Image.open(io.BytesIO(process_image(out.getvalue()).variants[0].body))

    red, _, _ = thumb.convert("RGB").getpixel((10, 10))  # type: ignore[misc]
    assert abs(red - 30_000 // 256) <= 2  # не белый 255


def test_unexpected_decoder_failure_is_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_: object, **__: object) -> Image.Image:
        raise RuntimeError("heif decoder failed")

    monkeypatch.setattr(Image, "open", broken)  # imaging берёт Image.open при вызове

    with pytest.raises(UnprocessableMediaError) as caught:
        process_image(photo("JPEG"))

    assert caught.value.reason is FailureReason.UNREADABLE


@pytest.mark.parametrize("mode", ["1", "P"])
def test_palette_and_bilevel_photos_are_scaled_smoothly(mode: str) -> None:
    # полосы в 1 px: без сглаживания уменьшение дало бы сплошной цвет, а не серый
    stripes = Image.new("L", (3200, 2400), 0)
    for x in range(0, 3200, 2):
        stripes.paste(255, (x, 0, x + 1, 2400))
    out = io.BytesIO()
    stripes.convert(mode).save(out, "PNG")

    lg = Image.open(io.BytesIO(process_image(out.getvalue()).variants[-1].body)).convert("L")

    assert 90 <= sum(lg.getdata()) / (lg.width * lg.height) <= 165


def test_multi_picture_jpeg_is_a_photo() -> None:
    frames = [Image.new("RGB", (2000, 1500), color) for color in ((200, 100, 50), (10, 20, 30))]
    out = io.BytesIO()
    frames[0].save(out, "MPO", save_all=True, append_images=frames[1:])

    result = process_image(out.getvalue())

    assert (result.width, result.height) == (1600, 1200)
