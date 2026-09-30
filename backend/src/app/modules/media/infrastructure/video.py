"""Обработка видео в воркере media (ARCHITECTURE §10.3, ADR-0007, шаг 2.2b): ffmpeg.

Вход недоверенный, поэтому:
- ролик скачивается потоком во временный каталог (до 200 MB — не в память); каталоги,
  брошенные убитым воркером, убираются перед следующей задачей;
- контейнер — только MP4/MOV по magic bytes, ffmpeg читает его демуксером `mov`
  принудительно и только протоколом `file`: плейлист HLS или concat под видом видео иначе
  заставил бы его читать чужие файлы и адреса (LFI/SSRF через m3u8); внешние ссылки MOV
  (dref) ffmpeg по умолчанию не открывает;
- ffprobe читает только заголовки контейнера и ничего не декодирует
  (`-nofind_stream_info`), отдаёт только нужные поля (теги в сотни мегабайт в воркер не
  попадают): видеокодек из белого списка, ≤ 60 с (`too_long`), кадр от 16 px до
  MAX_PIXELS (`too_many_pixels`), ≤ 240 кадров/с в среднем; обложка (attached_pic)
  видеопотоком не считается. Белого списка декодеров у ffprobe нет: он открывает декодеры
  всех потоков и с таким списком отказывал бы ролику с обложкой или звуком вне списка;
- декодирует только ffmpeg и только выбранные потоки — с белым списком декодеров по их
  именам (`-codec_whitelist`) и пределом кадра (`-max_pixels`): ни заголовок, солгавший
  ffprobe, ни смена SPS посреди потока их не обойдут; два потока декодера, один —
  фильтров; через `prlimit` — предел CPU и памяти процесса (в образе он есть; на macOS —
  только таймаут);
- stdout читается с пределом (процесс, превысивший его, убивается), от stderr — хвост.

Выход: H.264 yuv420p + AAC (стерео, 48 кГц), длинная сторона ≤ 1280 без увеличения и с
чётными сторонами, ≤ 30 кадров/с (лишние кадры отбрасываются до масштабирования), VBV
≤ 4 Мбит/с, `+faststart`, без метаданных (в контейнере нет и строки версии ffmpeg); HDR
(HLG/PQ с iPhone) — тонмаппинг в SDR bt709 после уменьшения кадра, где у ffmpeg есть
zscale. Поворот по матрице дисплея применяет ffmpeg. Кадр около первой секунды
видеодорожки — PNG для постера: его обрабатывает конвейер фото.

Кто виноват: не прошёл ffprobe или проверки — файл (`unsupported`, `too_long`, …);
перекодирование упало, зависло или процесс убит, нет ffmpeg — сбой обработки
(ProcessingCrashedError): задача повторится, после MAX_ATTEMPTS — `unreadable`.
"""

import asyncio
import hashlib
import json
import os
import shutil
import signal
import tempfile
import time
from collections import deque
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from app.modules.media.application.dto import ProcessedVideo
from app.modules.media.application.ports import ProcessingCrashedError, UnprocessableMediaError
from app.modules.media.domain.asset import FailureReason
from app.modules.media.infrastructure.processes import child_environment
from app.platform.storage.port import Bucket, StoragePort

log = structlog.get_logger(__name__)

MAX_SECONDS = 60
"""Ролик портфолио — до минуты (ADR-0007 п. 3)."""
DURATION_SLACK = 0.5
"""Дорожки смещены на миллисекунды: ролик «60,012 с» — всё ещё минутный."""
MAX_PIXELS = 4096 * 3072
"""4K-кадр телефона и камеры 4:3; больше — не ролик с телефона, а бомба."""
MIN_SIDE = 16
"""Меньше — не ролик; сторону в 1 px кодер H.264 (чётные стороны) не примет."""
MAX_INPUT_FPS = 240
LONG_SIDE = 1280
OUTPUT_FPS = 30
MAX_OUTPUT_BYTES = 48 * 1024 * 1024
"""60 с при VBV 4 Мбит/с — около 31 MB; больше — сбой, а не свойство файла."""
VIDEO_CODECS = frozenset({"h264", "hevc", "mpeg4"})
"""Телефоны пишут H.264 и HEVC; MPEG-4 — старые Android."""
AUDIO_CODECS = frozenset(
    {"aac", "alac", "mp3", "opus", "pcm_s16le", "pcm_s24le", "pcm_s16be", "pcm_s24be"}
)
"""Звук телефонов и камер (LPCM в MOV — big-endian); вне списка — отбрасывается, ролик
остаётся."""
DECODERS = VIDEO_CODECS | AUDIO_CODECS | {"mp3float"}
"""Белый список декодеров — по их именам: MP3 по умолчанию декодирует `mp3float`."""
HDR_TRANSFERS = frozenset({"smpte2084", "arib-std-b67"})
CONTAINER_BOXES = frozenset({b"ftyp", b"wide", b"free", b"skip", b"mdat", b"moov", b"pnot"})
"""Первый бокс MP4/MOV: у QuickTime файл не всегда начинается с ftyp."""
TIMEOUT = 120.0
MAX_TIMEOUT = 900.0
STDOUT_LIMIT = 16 * 1024 * 1024
"""PNG кадра 1280×720 — около 2 MB; ответ ffprobe — сотни байт."""
STDERR_TAIL = 4096
MEMORY_BYTES = 3 * 1024**3
TEMP_ROOT = "sosed-media-video"
STALE_AFTER = 3600


@dataclass(frozen=True, slots=True, kw_only=True)
class Probe:
    duration: float
    width: int
    height: int
    fps: float
    hdr: bool
    audio_index: int | None
    """Номер звуковой дорожки из белого списка; None — ролик без звука."""


class FfmpegVideoProcessor:
    """VideoProcessor на ffmpeg и ffprobe из PATH (образ backend и `brew install ffmpeg`)."""

    def __init__(
        self,
        storage: StoragePort,
        *,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
        timeout: float = TIMEOUT,
    ) -> None:
        self._storage = storage
        self._ffmpeg, self._ffprobe, self._timeout = ffmpeg, ffprobe, timeout
        self._tonemap: bool | None = None

    async def process(
        self, bucket: Bucket, key: str, *, max_bytes: int, etag: str | None
    ) -> ProcessedVideo:
        root = Path(tempfile.gettempdir()) / TEMP_ROOT
        await asyncio.to_thread(_sweep, root)
        with tempfile.TemporaryDirectory(dir=await asyncio.to_thread(_ensure, root)) as tmp:
            source, target = Path(tmp) / "source.mov", Path(tmp) / "video.mp4"
            await self._storage.download(bucket, key, source, max_bytes=max_bytes, etag=etag)
            if await asyncio.to_thread(_first_box, source) not in CONTAINER_BOXES:
                raise UnprocessableMediaError(FailureReason.UNSUPPORTED)
            probe = await self._probe(source)
            await self._transcode(source, target, probe)
            output = await self._probe(target)
            size = await asyncio.to_thread(_size, target)
            if size > MAX_OUTPUT_BYTES:
                raise ProcessingCrashedError(f"transcoded video is {size} bytes")
            return ProcessedVideo(
                width=output.width,
                height=output.height,
                duration_ms=round(output.duration * 1000),
                sha256=await asyncio.to_thread(_sha256, source),
                video=await asyncio.to_thread(target.read_bytes),
                poster=await self._poster(target, output.duration),
            )

    async def _probe(self, path: Path) -> Probe:
        stdout = await self._run(
            self._ffprobe,
            *_input_options(ffprobe=True),
            "-print_format", "json",
            "-show_entries",
            "stream=index,codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,"
            "nb_frames,duration,color_transfer:stream_disposition=attached_pic",
            str(path),
            seconds=self._timeout,
            faults=FailureReason.UNSUPPORTED,
        )  # fmt: skip
        return probed(stdout)

    async def _transcode(self, source: Path, target: Path, probe: Probe) -> None:
        tonemap = probe.hdr and await self._can_tonemap()
        await self._run(
            self._ffmpeg,
            *_transcode_args(source, target, probe, tonemap=tonemap),
            seconds=_budget(probe, self._timeout),
            faults=None,  # проверки файл прошёл: сбой перекодирования — не его вина
        )

    async def _poster(self, video: Path, duration: float) -> bytes:
        """Кадр около первой секунды; у короткого ролика — первый кадр."""
        for at in dict.fromkeys((min(1.0, duration / 2), 0.0)):
            frame = await self._run(
                self._ffmpeg,
                *_input_options(ss=at), "-i", str(video),
                "-frames:v", "1", "-f", "image2pipe", "-c:v", "png", "-",
                seconds=self._timeout,
                faults=None,
            )  # fmt: skip
            if frame:
                return frame
        raise UnprocessableMediaError(FailureReason.UNREADABLE)  # ни одного кадра

    async def _can_tonemap(self) -> bool:
        """zscale есть в ffmpeg образа (Debian), в Homebrew — нет: там HDR остаётся как есть."""
        if self._tonemap is None:
            filters = await self._run(
                self._ffmpeg, "-hide_banner", "-filters", seconds=self._timeout, faults=None
            )
            self._tonemap = b" zscale " in filters and b" tonemap " in filters
            if not self._tonemap:
                log.warning("ffmpeg_without_zscale_hdr_kept")
        return self._tonemap

    async def _run(
        self, program: str, *args: str, seconds: float, faults: FailureReason | None
    ) -> bytes:
        """Процесс с пределами: `faults` — причина отказа файла при ненулевом коде или
        лишнем выводе (ffprobe); None — и это сбой обработки (перекодирование, кадр)."""
        executable = shutil.which(program, path=child_environment().get("PATH"))
        if executable is None:  # под prlimit ошибка запуска выглядела бы кодом возврата
            raise ProcessingCrashedError(f"{program} is not installed")
        process = await asyncio.create_subprocess_exec(
            *_limited(executable, args, seconds),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=child_environment(),
            start_new_session=True,  # своя группа: убить — так со всеми, кого он запустил
        )
        stderr: deque[bytes] = deque()
        finished = False
        try:
            async with asyncio.timeout(seconds), asyncio.TaskGroup() as group:
                output = group.create_task(_bounded(process, STDOUT_LIMIT))
                group.create_task(_tail(process.stderr, stderr))
                group.create_task(process.wait())
            finished = True
        except TimeoutError as exc:
            raise ProcessingCrashedError(f"{program} took over {seconds:.0f}s") from exc
        finally:
            if not finished:  # таймаут или отмена задачи
                _kill(process)
                await process.wait()
        error = b"".join(stderr).decode(errors="replace")[-STDERR_TAIL:]
        stdout = output.result()
        if stdout is None:  # убит за лишний вывод
            if faults is None:
                raise ProcessingCrashedError(f"{program} wrote over {STDOUT_LIMIT} bytes")
            raise UnprocessableMediaError(faults)
        if process.returncode is not None and process.returncode < 0:  # убит: OOM, prlimit
            raise ProcessingCrashedError(f"{program} killed by signal {-process.returncode}")
        if process.returncode != 0:
            if faults is None:
                raise ProcessingCrashedError(f"{program} exited {process.returncode}: {error}")
            log.info("ffprobe_refused_file", error=error)
            raise UnprocessableMediaError(faults)
        return stdout


def probed(raw: bytes) -> Probe:
    """Решение по ответу ffprobe: видеопоток из белого списка и пределы."""
    try:
        info: dict[str, Any] = json.loads(raw)
        streams: Sequence[dict[str, Any]] = info.get("streams", [])
        video = next(
            s
            for s in streams
            if s.get("codec_type") == "video"
            and not s.get("disposition", {}).get("attached_pic")  # обложка — не видео
        )
        # длительность формата считает только find_stream_info: берём дорожку (mdhd)
        duration = float(video["duration"])
        width, height = int(video["width"]), int(video["height"])
        # r_frame_rate у VFR-роликов (запись экрана) бывает «90000/1»: верим среднему
        fps = _rate(video.get("avg_frame_rate")) or _rate(video.get("r_frame_rate"))
        frames = int(video.get("nb_frames") or 0)
    except (ValueError, KeyError, StopIteration, TypeError) as exc:
        raise UnprocessableMediaError(FailureReason.UNSUPPORTED) from exc
    if video.get("codec_name") not in VIDEO_CODECS:
        raise UnprocessableMediaError(FailureReason.UNSUPPORTED)
    if width * height > MAX_PIXELS:
        raise UnprocessableMediaError(FailureReason.TOO_MANY_PIXELS)
    if min(width, height) < MIN_SIDE:
        raise UnprocessableMediaError(FailureReason.UNSUPPORTED)
    if fps > MAX_INPUT_FPS or frames > MAX_SECONDS * MAX_INPUT_FPS:
        raise UnprocessableMediaError(FailureReason.UNSUPPORTED)
    if duration > MAX_SECONDS + DURATION_SLACK:
        raise UnprocessableMediaError(FailureReason.TOO_LONG)
    audio = next(
        (
            int(s["index"])
            for s in streams
            if s.get("codec_type") == "audio" and s.get("codec_name") in AUDIO_CODECS
        ),
        None,
    )
    return Probe(
        duration=duration,
        width=width,
        height=height,
        fps=fps,
        # 10-битный SDR в bt2020 у Android тонмаппинг только затемнил бы
        hdr=video.get("color_transfer") in HDR_TRANSFERS,
        audio_index=audio,
    )


def _rate(value: object) -> float:
    """`30000/1001` → 29.97; пусто или `0/0` — 0."""
    if not isinstance(value, str) or "/" not in value:
        return 0.0
    numerator, denominator = (float(part) for part in value.split("/", 1))
    return numerator / denominator if denominator else 0.0


def _budget(probe: Probe, base: float) -> float:
    """Время на перекодирование: минута 4K60 на двух ядрах — минуты, а не секунды."""
    pixels = max(1.0, probe.width * probe.height / (1920 * 1080))
    frames = max(1.0, min(probe.fps, 60.0) / OUTPUT_FPS)
    return min(MAX_TIMEOUT, max(base, 60 + 4 * probe.duration * pixels * frames))


def _input_options(*, ss: float | None = None, ffprobe: bool = False) -> list[str]:
    """Входные пределы. ffprobe только читает заголовки: пределы декодера ему не нужны."""
    if ffprobe:
        return ["-v", "error", "-nofind_stream_info", "-protocol_whitelist", "file", "-f", "mov"]
    seek = ["-ss", f"{ss:.3f}"] if ss else []
    return [
        "-nostdin", "-y", "-v", "error", "-filter_threads", "1",
        "-threads", "2",
        "-max_pixels", str(MAX_PIXELS),
        "-codec_whitelist", ",".join(sorted(DECODERS)),
        "-protocol_whitelist", "file",
        *seek, "-f", "mov",
    ]  # fmt: skip


def _transcode_args(source: Path, target: Path, probe: Probe, *, tonemap: bool) -> list[str]:
    filters = []
    if probe.fps > OUTPUT_FPS:  # лишние кадры — до масштабирования, а не после
        filters.append(f"fps={OUTPUT_FPS}")
    filters.append(
        f"scale=w='min({LONG_SIDE},iw)':h='min({LONG_SIDE},ih)'"
        ":force_original_aspect_ratio=decrease:force_divisible_by=2"
    )
    if tonemap:  # после уменьшения: кадр 4K во float32 — в девять раз дороже
        filters.append(
            "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
            "tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv"
        )
    filters.append("format=yuv420p")
    audio = (
        ["-map", f"0:{probe.audio_index}",
         "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "48000"]
        if probe.audio_index is not None
        else ["-an"]
    )  # fmt: skip
    colors = ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
    return [
        *_input_options(), "-i", str(source),
        "-t", f"{min(probe.duration, MAX_SECONDS):.3f}",
        "-map", "0:V:0", "-map_metadata", "-1", "-map_chapters", "-1",
        "-vf", ",".join(filters),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-maxrate", "4M", "-bufsize", "8M",
        *(colors if tonemap else []),
        *audio,
        "-movflags", "+faststart",
        "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
        "-threads", "2",
        str(target),
    ]  # fmt: skip


def _limited(executable: str, args: Sequence[str], seconds: float) -> list[str]:
    """Предел CPU и памяти процесса через prlimit (util-linux в образе; на macOS его нет)."""
    prlimit = shutil.which("prlimit")
    if prlimit is None:
        return [executable, *args]
    cpu = int(seconds * 4) + 10  # CPU-секунды — сумма по потокам декодера и кодера
    return [prlimit, f"--cpu={cpu}", f"--as={MEMORY_BYTES}", "--", executable, *args]


async def _bounded(process: asyncio.subprocess.Process, limit: int) -> bytes | None:
    """stdout целиком; больше `limit` — процесс убит, None."""
    if process.stdout is None:
        return b""
    chunks: list[bytes] = []
    size = 0
    while chunk := await process.stdout.read(64 * 1024):
        size += len(chunk)
        if size > limit:
            _kill(process)
            return None
        chunks.append(chunk)
    return b"".join(chunks)


async def _tail(stream: asyncio.StreamReader | None, tail: deque[bytes]) -> None:
    """Дочитать stderr до конца, храня только последние STDERR_TAIL байт."""
    if stream is None:
        return
    kept = 0
    while chunk := await stream.read(64 * 1024):
        tail.append(chunk)
        kept += len(chunk)
        while len(tail) > 1 and kept - len(tail[0]) >= STDERR_TAIL:
            kept -= len(tail.popleft())


def _kill(process: asyncio.subprocess.Process) -> None:
    """Процесс со всей его группой: потомок, державший трубы, не оставит нас ждать их EOF."""
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)


def _ensure(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    return root


def _sweep(root: Path) -> None:
    """Каталоги, брошенные убитым воркером (SIGKILL не даёт им удалиться), — прочь."""
    if not root.exists():
        return
    stale = time.time() - STALE_AFTER
    for entry in root.iterdir():
        try:
            if entry.stat().st_mtime < stale:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            continue


def _size(path: Path) -> int:
    return path.stat().st_size


def _first_box(path: Path) -> bytes:
    with path.open("rb") as file:
        return file.read(8)[4:8]


def _sha256(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.digest()
