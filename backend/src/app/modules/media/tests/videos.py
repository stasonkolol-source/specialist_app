"""Ролики для тестов media: генерирует ffmpeg (в CI и образе он есть — шаг 2.2b)."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

LOCATION = "+44.8125+020.4612/"
"""Геопозиция, как её пишет iPhone в com.apple.quicktime.location.ISO6709."""


HLG = ["-vf", "setparams=color_primaries=bt2020:color_trc=arib-std-b67:colorspace=bt2020nc"]
"""Теги HDR, как у iPhone (HLG в bt2020): тонмаппинг решают они, а не битность. Фильтром, а
не опциями `-color_*`: новый ffmpeg берёт цвет кодера из кадров."""


def clip(
    *,
    seconds: float = 2,
    size: tuple[int, int] = (640, 360),
    fps: int = 30,
    codec: str = "libx265",
    pix_fmt: str = "yuv420p",
    audio: str = "aac",
    rotation: int | None = None,
    location: bool = True,
    hdr: bool = False,
) -> bytes:
    """Ролик MOV с тестовой картинкой и звуком; по умолчанию — как с iPhone: HEVC и геопозиция.
    Нечётные стороны кодеры принимают только в 4:4:4 (`pix_fmt="yuv444p"`)."""
    with tempfile.TemporaryDirectory() as tmp:
        plain, rotated = Path(tmp) / "plain.mov", Path(tmp) / "rotated.mov"
        tags = (
            ["-metadata", f"location={LOCATION}",
             "-metadata", f"com.apple.quicktime.location.ISO6709={LOCATION}",
             "-movflags", "use_metadata_tags"]
            if location
            else []
        )  # fmt: skip
        tuning = ["-tag:v", "hvc1", "-x265-params", "log-level=error"] if codec == "libx265" else []
        _ffmpeg(
            "-f", "lavfi", "-i", f"testsrc=size={size[0]}x{size[1]}:rate={fps}",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
            "-t", str(seconds), "-c:v", codec, "-preset", "ultrafast", "-pix_fmt", pix_fmt,
            *tuning, *(HLG if hdr else []), "-c:a", audio, *tags, str(plain),
        )  # fmt: skip
        if rotation is None:
            return plain.read_bytes()
        _ffmpeg("-display_rotation", str(rotation), "-i", str(plain), "-c", "copy", *tags[4:],
                str(rotated))  # fmt: skip
        return rotated.read_bytes()


def with_cover(video: bytes) -> bytes:
    """Тот же ролик в MP4 с обложкой (attached_pic), как у роликов из редакторов. MOV обложку
    не пишет."""
    with tempfile.TemporaryDirectory() as tmp:
        source, cover, out = Path(tmp) / "in.mov", Path(tmp) / "cover.png", Path(tmp) / "out.mp4"
        source.write_bytes(video)
        _ffmpeg("-f", "lavfi", "-i", "color=c=red:size=300x300", "-frames:v", "1", str(cover))
        _ffmpeg("-i", str(cover), "-i", str(source), "-map", "0", "-map", "1", "-c", "copy",
                "-disposition:v:0", "attached_pic", str(out))  # fmt: skip
        return out.read_bytes()


def has_zscale() -> bool:
    """zscale (libzimg) есть в ffmpeg Debian и Ubuntu, в Homebrew — нет. Вызывается при
    сборе тестов, в том числе unit-прогоном CI, где ffmpeg ещё не установлен."""
    if shutil.which("ffmpeg") is None:
        return False
    command = ["ffmpeg", "-hide_banner", "-filters"]
    filters = subprocess.run(command, check=True, capture_output=True)  # noqa: S603 — наши аргументы
    return b" zscale " in filters.stdout


def probe(data: bytes) -> dict[str, object]:
    """ffprobe готового ролика: формат, потоки и теги."""
    with tempfile.NamedTemporaryFile(suffix=".mp4") as file:
        file.write(data)
        file.flush()
        result = subprocess.run(  # noqa: S603 — аргументы наши
            ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",  # noqa: S607
             file.name],
            check=True,
            capture_output=True,
        )  # fmt: skip
    parsed: dict[str, object] = json.loads(result.stdout)
    return parsed


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, capture_output=True)  # noqa: S603, S607
