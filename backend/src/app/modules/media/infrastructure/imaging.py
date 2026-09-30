"""Обработка фото (ARCHITECTURE §10.3, ADR-0007): Pillow и pillow-heif в дочернем процессе.

Недоверенный файл декодирует отдельный процесс `python -m app.modules.media.infrastructure.
imaging <каталог>` с таймаутом и лимитами CPU и памяти. Процессу не достаются секреты
воркера: окружение — белым списком, stdin закрыт. Он читает `source` из каталога, пишет туда
варианты и ответ `answer.json`; родитель доверяет только известным именам и причинам.

Кто виноват в сбое:
- файл — процесс сам называет причину (`unsupported`, `too_many_pixels`, `unreadable`):
  UnprocessableMediaError, файл получает `rejected`;
- не файл — таймаут, падение или убийство процесса (OOM-kill, рестарт стенда), ошибка
  в нашем коде, битый ответ: ProcessingCrashedError, задача повторится (MAX_ATTEMPTS).

Внутри процесса:
- тип — по содержимому (magic bytes): JPEG (и MPO), PNG, WebP, HEIC/HEIF; остальное —
  `unsupported`. Берётся основной кадр: у HEIF — primary, у анимации — первый;
- размер кадра проверяется до декодирования и после: больше MAX_PIXELS — `too_many_pixels`;
- JPEG декодируется сразу уменьшенным (draft), кадр уменьшается до 1600 px до поворота
  и цветовых преобразований: полноразмерных копий нет;
- поворот по EXIF, цвета — в sRGB по встроенному ICC (битый профиль — как есть), 16-битный
  серый — в 8 бит, палитра — в RGB до уменьшения (иначе Pillow уменьшает её без сглаживания);
- варианты WebP 320/800/1600 без метаданных (EXIF с GPS, XMP, ICC), ThumbHash.
"""

import asyncio
import base64
import hashlib
import io
import json
import resource
import sys
import tempfile
import traceback
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

import structlog
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError
from PIL.JpegImagePlugin import JpegImageFile

from app.modules.media.application.dto import ImageVariant, ProcessedImage
from app.modules.media.application.ports import ProcessingCrashedError, UnprocessableMediaError
from app.modules.media.domain.asset import VARIANT_SIDES, FailureReason
from app.modules.media.infrastructure.processes import child_environment
from app.modules.media.infrastructure.thumbhash import MAX_SIDE as HASH_SIDE
from app.modules.media.infrastructure.thumbhash import rgba_to_thumbhash

log = structlog.get_logger(__name__)

MAX_PIXELS = 64_000_000
"""64 MP: снимок любого телефона без уменьшения (Android отдаёт HEIC как есть), но не бомба."""
FORMATS = ("JPEG", "PNG", "WEBP", "HEIF")
"""MPO (снимки с двумя кадрами) Pillow открывает JPEG-плагином."""
QUALITY = 80
LARGEST = max(VARIANT_SIDES.values())
SOURCE = "source"
ANSWER = "answer.json"
TIMEOUT = 60.0
"""Секунд на файл: 64 MP HEIC декодируется за 2–3 с."""
CPU_SECONDS = 90
MEMORY_BYTES = 3 * 1024**3
"""Адресное пространство процесса: с запасом для 64 MP и потоков libheif, но не весь сервер."""
SIXTEEN_BIT = {"I;16", "I;16L", "I;16B", "I;16N", "I"}
NEAREST_ONLY = {"1", "P", "PA"}
"""Режимы, которые Pillow уменьшает без сглаживания: сначала — в полноцветный."""


class SubprocessImageProcessor:
    """ImageProcessor: файл обрабатывает дочерний процесс (см. docstring модуля)."""

    def __init__(self, *, timeout: float = TIMEOUT, command: Sequence[str] | None = None) -> None:
        self._timeout = timeout
        self._command = tuple(command) if command else (sys.executable, "-m", __name__)

    async def process(self, data: bytes) -> ProcessedImage:
        with tempfile.TemporaryDirectory(prefix="media-image-") as tmp:
            workdir = Path(tmp)
            await asyncio.to_thread((workdir / SOURCE).write_bytes, data)
            await self._run(workdir)
            return await asyncio.to_thread(_result, workdir)

    async def _run(self, workdir: Path) -> None:
        process = await asyncio.create_subprocess_exec(
            *self._command,
            str(workdir),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=child_environment(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), self._timeout)
        except TimeoutError as exc:
            raise ProcessingCrashedError(f"image processing took over {self._timeout}s") from exc
        finally:
            if process.returncode is None:  # таймаут или отмена задачи: процесс не бросаем
                process.kill()
                await process.wait()
        output = (stderr + stdout).decode(errors="replace")[-1000:]
        if process.returncode != 0:
            raise ProcessingCrashedError(
                f"image process exited with {process.returncode}: {output}"
            )
        if output:
            log.info("image_processing_output", output=output)


def _result(workdir: Path) -> ProcessedImage:
    """Разбор ответа процесса: только известные имена и причины — он недоверенный."""
    try:
        answer: dict[str, Any] = json.loads((workdir / ANSWER).read_bytes())
        if answer.get("fault") == "file":
            reason = FailureReason(answer["reason"])
        elif answer.get("ok") is True:
            return ProcessedImage(
                width=int(answer["width"]),
                height=int(answer["height"]),
                placeholder=str(answer["placeholder"]),
                sha256=bytes.fromhex(answer["sha256"]),
                variants=tuple(_variant(item, workdir) for item in answer["variants"]),
            )
        else:
            raise ProcessingCrashedError(f"image process failed: {answer.get('error', '?')}")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise ProcessingCrashedError(f"bad answer of image process: {exc!r}") from exc
    raise UnprocessableMediaError(reason)


def _variant(item: dict[str, Any], workdir: Path) -> ImageVariant:
    name = item["name"]
    if not isinstance(name, str) or name not in VARIANT_SIDES:
        raise ValueError(f"unknown variant {name!r}")
    return ImageVariant(
        name=name,
        width=int(item["width"]),
        height=int(item["height"]),
        body=(workdir / f"{name}.webp").read_bytes(),
    )


# --- дочерний процесс ---------------------------------------------------------------------


def main(argv: Sequence[str]) -> int:
    """Точка входа процесса: обработать `<каталог>/source`, ответ — `<каталог>/answer.json`."""
    workdir = Path(argv[1])
    _limit_resources()
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS  # Pillow сам откажет вдвое большему кадру
    try:
        result = process_image((workdir / SOURCE).read_bytes())
    except UnprocessableMediaError as exc:
        return _answer(workdir, {"fault": "file", "reason": exc.reason.value})
    except Exception as exc:  # noqa: BLE001 — не файл: сбой нашего кода, повтор задачи
        traceback.print_exc()
        return _answer(workdir, {"fault": "internal", "error": repr(exc)[:300]})
    for variant in result.variants:
        (workdir / f"{variant.name}.webp").write_bytes(variant.body)
    return _answer(
        workdir,
        {
            "ok": True,
            "width": result.width,
            "height": result.height,
            "placeholder": result.placeholder,
            "sha256": result.sha256.hex(),
            "variants": [
                {"name": v.name, "width": v.width, "height": v.height} for v in result.variants
            ],
        },
    )


def _answer(workdir: Path, payload: dict[str, Any]) -> int:
    (workdir / ANSWER).write_text(json.dumps(payload))
    return 0


def _limit_resources() -> None:
    """Лимиты процесса: CPU — всегда, память — где ОС её ограничивает (Linux)."""
    for limit, value in ((resource.RLIMIT_CPU, CPU_SECONDS), (resource.RLIMIT_AS, MEMORY_BYTES)):
        # macOS не даёт ограничить адресное пространство — там остаются таймаут и CPU
        with suppress(ValueError, OSError):
            resource.setrlimit(limit, (value, value))


def _configure() -> None:
    """HEIF — только основное изображение, без миниатюр, глубины и служебных слоёв.
    Повторная регистрация дешёвая и ничего не меняет — вызов на каждый файл."""
    import pillow_heif

    pillow_heif.register_heif_opener(thumbnails=False, depth_images=False, aux_images=False)


def process_image(data: bytes) -> ProcessedImage:
    """Варианты без метаданных и плейсхолдер. Файл не подходит — UnprocessableMediaError;
    ошибка после декодирования — наша, она уходит как есть."""
    _configure()
    try:
        image = _normalized(data)
    except (Image.DecompressionBombError, MemoryError) as exc:
        raise UnprocessableMediaError(FailureReason.TOO_MANY_PIXELS) from exc
    except UnidentifiedImageError as exc:
        raise UnprocessableMediaError(FailureReason.UNSUPPORTED) from exc
    except (OSError, ValueError, SyntaxError, EOFError, RuntimeError, IndexError) as exc:
        raise UnprocessableMediaError(FailureReason.UNREADABLE) from exc
    variants = _variants(image)
    largest = variants[-1]
    return ProcessedImage(
        width=largest.width,
        height=largest.height,
        placeholder=placeholder_of(image),
        sha256=hashlib.sha256(data).digest(),
        variants=variants,
    )


def _ensure_pixels(size: tuple[int, int]) -> None:
    if size[0] * size[1] > MAX_PIXELS:
        raise UnprocessableMediaError(FailureReason.TOO_MANY_PIXELS)


def _normalized(data: bytes) -> Image.Image:
    """Основной кадр не больше 1600 px, повёрнутый по EXIF, в sRGB и RGB/RGBA, без метаданных."""
    with Image.open(io.BytesIO(data), formats=FORMATS) as source:
        _ensure_pixels(source.size)
        if isinstance(source, JpegImageFile):  # и MPO: libjpeg сразу уменьшит в 2–8 раз
            source.draft("RGB", _fit(source.size))
        source.load()
        _ensure_pixels(source.size)
        icc = source.info.get("icc_profile")
        orientation = source.getexif().get(0x0112)  # ExifTags.Base.Orientation
        frame = _full_color(source)
        frame.thumbnail((LARGEST, LARGEST), Image.Resampling.LANCZOS)  # на месте, без копии
        image = _oriented(frame, orientation)  # уже маленький кадр
    image = _eight_bit(image)
    image = _srgb(image, icc)
    image.info.clear()  # EXIF, XMP, ICC и комментарии в варианты не попадут
    return image


def _fit(size: tuple[int, int]) -> tuple[int, int]:
    """Размер, до которого draft может уменьшить кадр, не опустившись ниже 1600 px."""
    scale = min(1.0, LARGEST / max(size))
    return max(1, int(size[0] * scale)), max(1, int(size[1] * scale))


def _full_color(image: Image.Image) -> Image.Image:
    """Палитра и 1 бит — в полноцветный режим до уменьшения, чтобы уменьшать со сглаживанием."""
    if image.mode not in NEAREST_ONLY:
        return image
    return image.convert("RGBA" if _has_alpha(image) else ("L" if image.mode == "1" else "RGB"))


def _oriented(image: Image.Image, orientation: object) -> Image.Image:
    """Поворот по EXIF-ориентации исходного кадра (у копии после convert её уже нет)."""
    if isinstance(orientation, int) and orientation != 1:
        exif = image.getexif()
        exif[0x0112] = orientation
        image.info["exif"] = exif.tobytes()
    return ImageOps.exif_transpose(image)


def _eight_bit(image: Image.Image) -> Image.Image:
    """16-битный серый (PNG) → 8 бит: convert('RGB') обрезал бы его до белого."""
    if image.mode in SIXTEEN_BIT:
        return image.convert("I").point(lambda value: value * (1 / 256)).convert("L")
    return image


def _has_alpha(image: Image.Image) -> bool:
    return image.mode in {"RGBA", "LA", "PA"} or (
        image.mode == "P" and "transparency" in image.info
    )


def _srgb(image: Image.Image, icc: bytes | None) -> Image.Image:
    """Цвета по встроенному профилю — в sRGB: без профиля WebP показывают как sRGB."""
    mode = "RGBA" if _has_alpha(image) else "RGB"
    if icc and image.mode in {"RGB", "RGBA", "CMYK", "L"}:
        try:
            converted = ImageCms.profileToProfile(
                image,
                ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                ImageCms.createProfile("sRGB"),
                outputMode=mode if image.mode != "CMYK" else "RGB",
            )
            if converted is not None:
                image = converted
        except ImageCms.PyCMSError, OSError, ValueError:
            pass  # битый профиль: цвета как есть
    return image if image.mode == mode else image.convert(mode)


def _variants(image: Image.Image) -> tuple[ImageVariant, ...]:
    """Варианты по возрастанию; фото меньше следующего размера его не получает: без
    увеличения он совпал бы с предыдущим."""
    variants: list[ImageVariant] = []
    for name, side in VARIANT_SIDES.items():
        if variants and max(image.size) <= max(variants[-1].width, variants[-1].height):
            break
        variants.append(webp_variant(image, name, side))
    return tuple(variants)


def webp_variant(image: Image.Image, name: str, side: int) -> ImageVariant:
    variant = image.copy()
    variant.thumbnail((side, side), Image.Resampling.LANCZOS)  # без увеличения
    body = io.BytesIO()
    variant.save(body, "WEBP", quality=QUALITY, method=4)
    return ImageVariant(name=name, width=variant.width, height=variant.height, body=body.getvalue())


def placeholder_of(image: Image.Image) -> str:
    small = image.copy()
    small.thumbnail((HASH_SIDE, HASH_SIDE), Image.Resampling.BILINEAR)
    rgba = small.convert("RGBA")
    return base64.b64encode(rgba_to_thumbhash(rgba.width, rgba.height, rgba.tobytes())).decode()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
