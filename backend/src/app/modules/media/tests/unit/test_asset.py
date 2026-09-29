"""Жизненный цикл файла (ARCHITECTURE §7.9): pending_upload → uploaded → …, deleted."""

from datetime import UTC, datetime

import pytest

from app.modules.media.domain.asset import (
    FailureReason,
    MediaAsset,
    MediaStatus,
    Variant,
    variant_key,
)
from app.modules.media.domain.policy import MediaKind, MediaPurpose
from app.modules.media.errors import MediaStateError
from app.platform.contracts.events.media import MediaReady, MediaRejected, MediaUploaded
from app.platform.kernel.ids import MediaId, UserId, new_id

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
ETAG = "a1b2c3"


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

    a.complete(size_bytes=1000, mime_type="image/jpeg", etag=ETAG, now=NOW)

    assert (a.status, a.uploaded_at, a.etag) == (MediaStatus.UPLOADED, NOW, ETAG)
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
    a.complete(size_bytes=1000, mime_type="image/jpeg", etag=ETAG, now=NOW)
    a.pull_events()

    a.complete(size_bytes=1000, mime_type="image/jpeg", etag=ETAG, now=NOW)

    assert a.status is MediaStatus.UPLOADED
    assert a.pull_events() == []


@pytest.mark.parametrize(("size", "mime"), [(999, "image/jpeg"), (1000, "image/png")])
def test_file_not_matching_the_declaration_fails(size: int, mime: str) -> None:
    a = asset()

    a.complete(size_bytes=size, mime_type=mime, etag=ETAG, now=NOW)

    assert (a.status, a.failure_reason) == (MediaStatus.FAILED, FailureReason.MISMATCH)
    assert a.etag is None  # не тот файл — его ETag не нужен
    assert a.pull_events() == []
    with pytest.raises(MediaStateError):
        a.complete(size_bytes=1000, mime_type="image/jpeg", etag=ETAG, now=NOW)


def test_abandoned_upload_fails() -> None:
    a = asset()

    a.abandon()

    assert (a.status, a.failure_reason) == (MediaStatus.FAILED, FailureReason.ABANDONED)


def test_delete_is_soft_and_repeatable() -> None:
    a = asset()

    assert a.delete(now=NOW) is True
    assert a.delete(now=NOW) is False
    assert (a.status, a.deleted_at) == (MediaStatus.DELETED, NOW)


def uploaded() -> MediaAsset:
    a = asset()
    a.complete(size_bytes=1000, mime_type="image/jpeg", etag=ETAG, now=NOW)
    a.pull_events()
    return a


def variants(a: MediaAsset) -> dict[str, Variant]:
    return {"thumb": Variant(key=variant_key(a.id, "thumb"), width=320, height=240)}


def test_processing_ends_ready_with_variants_and_announces_it() -> None:
    a = uploaded()

    assert a.start_processing() is True
    assert a.start_processing() is True  # повтор задачи после сбоя продолжает
    assert (a.attempts, a.out_of_attempts) == (2, False)
    a.ready(
        width=640, height=480, placeholder="hash", sha256=b"s" * 32, variants=variants(a), now=NOW
    )

    assert (a.status, a.processed_at, a.width, a.placeholder) == (
        MediaStatus.READY,
        NOW,
        640,
        "hash",
    )
    assert a.variants["thumb"].key == f"m/{a.id}/thumb.webp"
    [event] = a.pull_events()
    assert isinstance(event, MediaReady)
    assert (event.media_id, event.kind, event.purpose) == (a.id, "image", "portfolio")
    assert a.start_processing() is False  # готовый файл повтор не трогает


def test_processing_can_reject_the_file() -> None:
    a = uploaded()
    a.start_processing()

    a.reject(FailureReason.TOO_MANY_PIXELS, now=NOW)

    assert (a.status, a.failure_reason) == (MediaStatus.REJECTED, FailureReason.TOO_MANY_PIXELS)
    [event] = a.pull_events()
    assert isinstance(event, MediaRejected)
    assert event.reason == "too_many_pixels"


def test_results_need_a_file_in_processing() -> None:
    a = uploaded()

    with pytest.raises(MediaStateError):
        a.ready(width=1, height=1, placeholder="", sha256=b"", variants={}, now=NOW)
    with pytest.raises(MediaStateError):
        a.reject(FailureReason.UNREADABLE, now=NOW)


def test_deleted_file_is_not_processed() -> None:
    a = uploaded()
    a.delete(now=NOW)

    assert a.start_processing() is False


def test_purge_lists_original_and_variants() -> None:
    a = uploaded()
    a.start_processing()
    a.ready(width=640, height=480, placeholder="h", sha256=b"s", variants=variants(a), now=NOW)
    a.delete(now=NOW)

    a.purge(now=NOW)

    assert a.purged_at == NOW
    # все возможные варианты в обоих бакетах: удалённый файл прячет их в private
    assert a.objects()[0] == ("incoming", a.object_key)
    assert set(a.objects()[1:]) == {
        (bucket, f"m/{a.id}/{name}.webp")
        for name in ("thumb", "md", "lg")
        for bucket in ("media", "private")
    }


def test_only_deleted_files_are_purged() -> None:
    with pytest.raises(MediaStateError):
        uploaded().purge(now=NOW)


def test_third_crash_uses_up_the_attempts() -> None:
    a = uploaded()
    for _ in range(3):
        a.start_processing()

    assert a.out_of_attempts is True


def test_giving_up_rejects_the_file_as_unreadable() -> None:
    a = uploaded()  # зависло ещё до первого запуска

    a.give_up(now=NOW)

    assert (a.status, a.failure_reason) == (MediaStatus.REJECTED, FailureReason.UNREADABLE)
    [event] = a.pull_events()
    assert isinstance(event, MediaRejected)


def test_only_deleted_files_are_hidden() -> None:
    a = uploaded()
    with pytest.raises(MediaStateError):
        a.hide(now=NOW)

    a.delete(now=NOW)
    a.hide(now=NOW)

    assert a.hidden_at == NOW
