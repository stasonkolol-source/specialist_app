"""Видео (DEVELOPMENT_PLAN 2.2b, ARCHITECTURE §10.3): ffmpeg.

«Готово, когда»: HEVC → MP4 H.264 без метаданных и с постером; ролик длиннее 60 с →
`rejected`; повтор задачи не плодит файлы (ключи неизменяемые — API-тест обработки).
Здесь — настоящий ffmpeg на роликах, какие снимают телефоны, камеры и редакторы.
"""

import asyncio
import io
import stat
from pathlib import Path
from typing import cast

import pytest
from PIL import Image

from app.modules.media.application.dto import ProcessedVideo
from app.modules.media.application.ports import ProcessingCrashedError, UnprocessableMediaError
from app.modules.media.domain.asset import FailureReason
from app.modules.media.infrastructure.video import FfmpegVideoProcessor
from app.modules.media.tests.videos import LOCATION, clip, has_zscale, probe, with_cover
from app.platform.storage.port import Bucket, StoragePort

pytestmark = pytest.mark.integration


class LocalStorage:
    """Хранилище из одного файла: скачивание — копия байтов."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    async def download(
        self, bucket: Bucket, key: str, target: Path, *, max_bytes: int, etag: str | None = None
    ) -> None:
        await asyncio.to_thread(target.write_bytes, self._data)


def processor(data: bytes, **options: object) -> FfmpegVideoProcessor:
    return FfmpegVideoProcessor(cast(StoragePort, LocalStorage(data)), **options)  # type: ignore[arg-type]


async def process(data: bytes, **options: object) -> ProcessedVideo:
    return await processor(data, **options).process(
        Bucket.INCOMING, "portfolio/x/original", max_bytes=len(data), etag=None
    )


def streams(video: ProcessedVideo) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], probe(video.video)["streams"])


def script(tmp_path: Path, name: str, body: str) -> str:
    """Подставной ffmpeg или ffprobe."""
    path = tmp_path / name
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


async def test_iphone_hevc_becomes_h264_without_location_and_gets_a_poster() -> None:
    source = clip(rotation=90)  # HEVC, геопозиция, «снято вертикально»

    video = await processor(source).process(Bucket.INCOMING, "k", max_bytes=len(source), etag=None)

    info = probe(video.video)
    streams = cast(list[dict[str, object]], info["streams"])
    kinds = {s["codec_type"]: s for s in streams}
    assert kinds["video"]["codec_name"] == "h264"
    assert kinds["video"]["pix_fmt"] == "yuv420p"
    assert (kinds["video"]["width"], kinds["video"]["height"]) == (360, 640)  # повёрнут
    assert kinds["audio"]["codec_name"] == "aac"
    assert LOCATION not in str(info)  # геопозиции нет нигде: ни в формате, ни в потоках
    assert LOCATION.encode() not in video.video  # и в байтах файла тоже
    assert (video.width, video.height) == (360, 640)
    assert 1900 <= video.duration_ms <= 2100
    poster = Image.open(io.BytesIO(video.poster))
    assert (poster.format, poster.size) == ("PNG", (360, 640))
    assert len(video.sha256) == 32


async def test_clip_longer_than_a_minute_is_refused() -> None:
    long = clip(seconds=61, size=(64, 64), fps=1, codec="libx264", location=False)

    with pytest.raises(UnprocessableMediaError) as caught:
        await process(long)

    assert caught.value.reason is FailureReason.TOO_LONG


async def test_playlist_pretending_to_be_a_video_is_refused_before_ffmpeg() -> None:
    # HLS читал бы чужие файлы и адреса: до ffmpeg он не доходит
    playlist = b"#EXTM3U\n#EXTINF:1,\nfile:///etc/passwd\n#EXT-X-ENDLIST\n"

    with pytest.raises(UnprocessableMediaError) as caught:
        await process(playlist)

    assert caught.value.reason is FailureReason.UNSUPPORTED


async def test_broken_clip_is_unreadable() -> None:
    broken = clip(codec="libx264", location=False)[:3000]  # оборван посреди данных

    with pytest.raises(UnprocessableMediaError) as caught:
        await process(broken)

    assert caught.value.reason in {FailureReason.UNREADABLE, FailureReason.UNSUPPORTED}


async def test_hung_or_missing_ffmpeg_is_a_crash_not_the_files_fault(tmp_path: Path) -> None:
    hung = tmp_path / "ffprobe"
    hung.write_text("#!/bin/sh\nsleep 30\n")
    hung.chmod(hung.stat().st_mode | stat.S_IEXEC)
    source = clip(codec="libx264", location=False)

    with pytest.raises(ProcessingCrashedError):
        await process(source, ffprobe=str(hung), timeout=1.0)
    with pytest.raises(ProcessingCrashedError):
        await process(source, ffprobe=str(tmp_path / "missing"))


async def test_odd_sized_clip_gets_even_sides() -> None:
    odd = clip(size=(641, 361), codec="libx264", pix_fmt="yuv444p", location=False)

    video = await process(odd)

    picture = streams(video)[0]
    assert (picture["width"], picture["height"], picture["pix_fmt"]) == (640, 360, "yuv420p")


async def test_cover_art_is_neither_taken_for_the_video_nor_kept() -> None:
    edited = with_cover(clip(codec="libx264", location=False))  # ролик из редактора

    video = await process(edited)

    assert [(s["codec_type"], s["codec_name"]) for s in streams(video)] == [
        ("video", "h264"),
        ("audio", "aac"),
    ]
    assert (video.width, video.height) == (640, 360)


async def test_camera_pcm_sound_is_kept_and_unknown_sound_dropped() -> None:
    camera = await process(clip(codec="libx264", audio="pcm_s16be", location=False))
    assert [s["codec_name"] for s in streams(camera)] == ["h264", "aac"]

    dolby = await process(clip(codec="libx264", audio="ac3", location=False))
    assert [s["codec_name"] for s in streams(dolby)] == ["h264"]  # ролик остался, звук — нет


async def test_a_minute_with_track_offsets_passes_cut_to_a_minute() -> None:
    minute = clip(seconds=60.3, size=(64, 64), fps=10, codec="libx264", location=False)

    video = await process(minute)

    assert 59_900 <= video.duration_ms <= 60_000


async def test_high_frame_rate_is_reduced_to_thirty() -> None:
    fast = clip(size=(320, 180), fps=60, codec="libx264", location=False)

    video = await process(fast)

    assert streams(video)[0]["avg_frame_rate"] == "30/1"


@pytest.mark.skipif(not has_zscale(), reason="ffmpeg без zscale (Homebrew): HDR остаётся")
async def test_hdr_is_tonemapped_to_sdr() -> None:
    hlg = clip(codec="libx264", hdr=True, location=False)

    video = await process(hlg)

    picture = streams(video)[0]
    assert (picture["color_transfer"], picture["color_primaries"]) == ("bt709", "bt709")


async def test_floods_of_output_are_cut_off(tmp_path: Path) -> None:
    source = clip(codec="libx264", location=False)
    # stderr — только хвост: 40 MB в память воркера не попадают
    noisy = script(tmp_path, "noisy", "head -c 40000000 /dev/zero >&2; exit 1")
    with pytest.raises(UnprocessableMediaError) as caught:
        await process(source, ffprobe=noisy)
    assert caught.value.reason is FailureReason.UNSUPPORTED

    # stdout сверх предела — процесс убит: у ffprobe это отказ файла, у ffmpeg — сбой
    chatty = script(tmp_path, "chatty", "head -c 40000000 /dev/zero")
    with pytest.raises(UnprocessableMediaError):
        await process(source, ffprobe=chatty)
    with pytest.raises(ProcessingCrashedError):
        await process(source, ffmpeg=chatty)
