"""Что и как можно загрузить (ARCHITECTURE §10.1)."""

import pytest

from app.modules.media.domain.policy import (
    MB,
    MULTIPART_THRESHOLD,
    MediaKind,
    MediaPurpose,
    upload_rule,
)
from app.modules.media.errors import (
    MediaPurposeNotAvailableError,
    MediaTooLargeError,
    UnsupportedMediaTypeError,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("purpose", "mime", "size", "kind", "multipart"),
    [
        (MediaPurpose.AVATAR, "image/jpeg", 10 * MB, MediaKind.IMAGE, False),
        (MediaPurpose.PORTFOLIO, "image/heic", 15 * MB, MediaKind.IMAGE, False),
        (MediaPurpose.PORTFOLIO, "video/mp4", MULTIPART_THRESHOLD, MediaKind.VIDEO, False),
        (MediaPurpose.PORTFOLIO, "video/quicktime", MULTIPART_THRESHOLD + 1, MediaKind.VIDEO, True),
        (MediaPurpose.JOB, "image/webp", 1, MediaKind.IMAGE, False),
    ],
    ids=["avatar", "portfolio-heic", "video-50mb-one-put", "video-over-50mb-parts", "job"],
)
def test_allowed_uploads(
    purpose: MediaPurpose, mime: str, size: int, kind: MediaKind, multipart: bool
) -> None:
    rule = upload_rule(purpose, mime, size)

    assert (rule.kind, rule.multipart) == (kind, multipart)


@pytest.mark.parametrize(
    ("purpose", "mime", "size", "error"),
    [
        (MediaPurpose.AVATAR, "image/jpeg", 10 * MB + 1, MediaTooLargeError),
        (MediaPurpose.PORTFOLIO, "video/mp4", 200 * MB + 1, MediaTooLargeError),
        (MediaPurpose.JOB, "video/mp4", MB, UnsupportedMediaTypeError),  # к заявке — только фото
        (MediaPurpose.AVATAR, "application/zip", MB, UnsupportedMediaTypeError),
        (MediaPurpose.AVATAR, "image/svg+xml", MB, UnsupportedMediaTypeError),
        (MediaPurpose.PORTFOLIO, "application/pdf", MB, UnsupportedMediaTypeError),
        (MediaPurpose.MESSAGE, "image/jpeg", MB, MediaPurposeNotAvailableError),
        (MediaPurpose.VERIFICATION, "application/pdf", MB, MediaPurposeNotAvailableError),
    ],
    ids=[
        "avatar-too-big",
        "video-too-big",
        "video-to-job",
        "zip",
        "svg",
        "pdf-to-portfolio",
        "messages-are-v1",
        "verification-is-v1",
    ],
)
def test_refused_uploads(
    purpose: MediaPurpose, mime: str, size: int, error: type[Exception]
) -> None:
    with pytest.raises(error):
        upload_rule(purpose, mime, size)


def test_too_large_error_names_the_limit_in_megabytes() -> None:
    with pytest.raises(MediaTooLargeError) as caught:
        upload_rule(MediaPurpose.JOB, "image/jpeg", 16 * MB)

    assert caught.value.params == {"max_bytes": 15 * MB, "max_mb": 15}
