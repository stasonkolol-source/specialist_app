"""Жизненный цикл файла (ARCHITECTURE §7.9): pending_upload → uploaded → …, deleted."""

from datetime import UTC, datetime

import pytest

from app.modules.media.domain.asset import (
    FailureReason,
    MediaAsset,
    MediaStatus,
)
from app.modules.media.domain.policy import MediaKind, MediaPurpose
from app.modules.media.errors import MediaStateError
from app.platform.contracts.events.media import MediaUploaded
from app.platform.kernel.ids import MediaId, UserId, new_id

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


def asset(**overrides: object) -> MediaAsset:
    values: dict[str, object] = {
        "media_id": MediaId(new_id()),
        "owner_id": UserId(new_id()),
        "kind": MediaKind.IMAGE,
        "purpose": MediaPurpose.PORTFOLIO,
        "mime_type": "image/jpeg",
        "size_bytes": 1000,
        "now": NOW,
    }
    return MediaAsset.start(**(values | overrides))  # type: ignore[arg-type]


def test_new_upload_waits_in_incoming_under_server_chosen_key() -> None:
    a = asset()

    assert (a.status, a.bucket, a.multipart) == (MediaStatus.PENDING_UPLOAD, "incoming", False)
    assert a.object_key == f"portfolio/2026/10/{a.id}/original"


def test_complete_marks_uploaded_and_announces_processing() -> None:
    a = asset()

    a.complete(size_bytes=1000, mime_type="image/jpeg", now=NOW)

    assert (a.status, a.uploaded_at) == (MediaStatus.UPLOADED, NOW)
    [event] = a.pull_events()
    assert isinstance(event, MediaUploaded)
    assert (event.media_id, event.owner_id, event.kind, event.purpose) == (
        a.id,
        a.owner_id,
        "image",
        "portfolio",
    )


def test_repeated_complete_changes_nothing() -> None:
    a = asset()
    a.complete(size_bytes=1000, mime_type="image/jpeg", now=NOW)
    a.pull_events()

    a.complete(size_bytes=1000, mime_type="image/jpeg", now=NOW)

    assert a.status is MediaStatus.UPLOADED
    assert a.pull_events() == []


@pytest.mark.parametrize(("size", "mime"), [(999, "image/jpeg"), (1000, "image/png")])
def test_file_not_matching_the_declaration_fails(size: int, mime: str) -> None:
    a = asset()

    a.complete(size_bytes=size, mime_type=mime, now=NOW)

    assert (a.status, a.failure_reason) == (MediaStatus.FAILED, FailureReason.MISMATCH)
    assert a.pull_events() == []
    with pytest.raises(MediaStateError):
        a.complete(size_bytes=1000, mime_type="image/jpeg", now=NOW)


def test_abandoned_upload_fails() -> None:
    a = asset()

    a.abandon()

    assert (a.status, a.failure_reason) == (MediaStatus.FAILED, FailureReason.ABANDONED)


def test_delete_is_soft_and_repeatable() -> None:
    a = asset()

    assert a.delete(now=NOW) is True
    assert a.delete(now=NOW) is False
    assert (a.status, a.deleted_at) == (MediaStatus.DELETED, NOW)
