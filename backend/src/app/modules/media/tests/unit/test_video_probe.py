"""Решение по ответу ffprobe (шаг 2.2b): какой поток — ролик, пределы и HDR.

ffprobe читает только заголовки контейнера (`-nofind_stream_info`): длительность — дорожки,
а не формата; обложка (attached_pic) — видеопоток, но не ролик.
"""

import json
from typing import Any

import pytest

from app.modules.media.application.ports import UnprocessableMediaError
from app.modules.media.domain.asset import FailureReason
from app.modules.media.infrastructure.video import probed

pytestmark = pytest.mark.unit


def video(**fields: Any) -> dict[str, Any]:
    stream = {
        "index": 0,
        "codec_type": "video",
        "codec_name": "hevc",
        "width": 1920,
        "height": 1080,
        "r_frame_rate": "30/1",
        "avg_frame_rate": "30/1",
        "nb_frames": "300",
        "duration": "10.000000",
        "disposition": {"attached_pic": 0},
    }
    return {**stream, **fields}


def audio(index: int, codec: str) -> dict[str, Any]:
    return {"index": index, "codec_type": "audio", "codec_name": codec, "duration": "10.0"}


def answer(*streams: dict[str, Any]) -> bytes:
    return json.dumps({"streams": list(streams)}).encode()


def refused(*streams: dict[str, Any]) -> FailureReason:
    with pytest.raises(UnprocessableMediaError) as caught:
        probed(answer(*streams))
    return caught.value.reason


def test_iphone_clip_is_accepted() -> None:
    probe = probed(answer(video(color_transfer="arib-std-b67"), audio(1, "aac")))

    assert (probe.width, probe.height, probe.duration, probe.fps) == (1920, 1080, 10.0, 30.0)
    assert probe.hdr is True  # HLG iPhone
    assert probe.audio_index == 1


def test_cover_art_is_not_the_video() -> None:
    cover = video(index=0, codec_name="png", width=300, height=300, disposition={"attached_pic": 1})

    probe = probed(answer(cover, video(index=1, width=1280, height=720), audio(2, "aac")))

    assert (probe.width, probe.height) == (1280, 720)


def test_only_cover_art_is_not_a_video() -> None:
    cover = video(codec_name="mjpeg", disposition={"attached_pic": 1})

    assert refused(cover, audio(1, "aac")) is FailureReason.UNSUPPORTED


def test_audio_outside_the_list_is_dropped_not_the_clip() -> None:
    probe = probed(answer(video(), audio(1, "eac3"), audio(2, "pcm_s16be")))
    assert probe.audio_index == 2  # LPCM камеры

    assert probed(answer(video(), audio(1, "ac3"))).audio_index is None  # ролик без звука


def test_variable_frame_rate_is_judged_by_the_average() -> None:
    # запись экрана: r_frame_rate — наименьшее общее кратное, а не частота кадров
    probe = probed(answer(video(r_frame_rate="90000/1", avg_frame_rate="30000/1001")))

    assert probe.fps == pytest.approx(29.97, abs=0.01)


def test_ten_bit_sdr_in_bt2020_is_not_hdr() -> None:
    assert probed(answer(video(color_transfer="bt2020-10"))).hdr is False
    assert probed(answer(video(color_transfer="smpte2084"))).hdr is True  # PQ, HDR10


@pytest.mark.parametrize(
    ("stream", "reason"),
    [
        (video(codec_name="prores"), FailureReason.UNSUPPORTED),
        (video(width=8192, height=4320), FailureReason.TOO_MANY_PIXELS),
        (video(width=8, height=720), FailureReason.UNSUPPORTED),  # меньше 16 px
        (video(avg_frame_rate="480/1"), FailureReason.UNSUPPORTED),
        (video(nb_frames="100000"), FailureReason.UNSUPPORTED),  # кадровая бомба
        (video(duration="60.600000"), FailureReason.TOO_LONG),
        ({k: v for k, v in video().items() if k != "duration"}, FailureReason.UNSUPPORTED),
    ],
    ids=["codec", "pixels", "tiny", "fps", "frames", "too-long", "no-duration"],
)
def test_limits(stream: dict[str, Any], reason: FailureReason) -> None:
    assert refused(stream) is reason


def test_a_minute_with_track_offsets_is_still_a_minute() -> None:
    assert probed(answer(video(duration="60.400000"))).duration == pytest.approx(60.4)


def test_garbage_is_unsupported() -> None:
    with pytest.raises(UnprocessableMediaError) as caught:
        probed(b"not json")

    assert caught.value.reason is FailureReason.UNSUPPORTED
