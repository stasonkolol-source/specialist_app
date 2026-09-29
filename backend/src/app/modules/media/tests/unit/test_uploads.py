"""Ссылки на загрузку: одним PUT или частями (ADR-0007, спайк 0.24)."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.media.application.uploads import part_count, part_size, upload_plan
from app.modules.media.application.use_cases.complete_upload import ensure_all_parts
from app.modules.media.domain.asset import MediaAsset
from app.modules.media.domain.policy import MB, MediaKind, MediaPurpose
from app.modules.media.errors import UploadIncompleteError
from app.platform.kernel.errors import DomainValidationError
from app.platform.kernel.ids import MediaId, UserId, new_id
from app.platform.storage.port import (
    PART_SIZE,
    Bucket,
    PresignedRequest,
    StoredObject,
    UploadedPart,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


class FakeStorage:
    """Подпись без сети: адрес содержит ключ, размер и номер части."""

    async def presign_put(
        self,
        bucket: Bucket,
        key: str,
        *,
        content_type: str,
        size: int,
        ttl: timedelta = timedelta(),
    ) -> PresignedRequest:
        return PresignedRequest(
            method="PUT",
            url=f"https://s3/{bucket}/{key}?size={size}",
            expires_at=NOW + timedelta(minutes=10),
            headers={"Content-Type": content_type},
        )

    async def presign_part(
        self,
        bucket: Bucket,
        key: str,
        *,
        upload_id: str,
        part_number: int,
        size: int,
        ttl: timedelta = timedelta(),
    ) -> PresignedRequest:
        return PresignedRequest(
            method="PUT",
            url=f"https://s3/{bucket}/{key}?part={part_number}&size={size}&upload={upload_id}",
            expires_at=NOW + timedelta(minutes=10),
        )

    async def start_multipart(self, bucket: Bucket, key: str, *, content_type: str) -> str:
        raise NotImplementedError

    async def complete_multipart(
        self, bucket: Bucket, key: str, *, upload_id: str, parts: Sequence[UploadedPart]
    ) -> None:
        raise NotImplementedError

    async def abort_multipart(self, bucket: Bucket, key: str, *, upload_id: str) -> None:
        raise NotImplementedError

    async def head(self, bucket: Bucket, key: str) -> StoredObject | None:
        raise NotImplementedError

    async def presign_get(self, bucket: Bucket, key: str, *, ttl: timedelta = timedelta()) -> str:
        raise NotImplementedError

    async def get(
        self, bucket: Bucket, key: str, *, max_bytes: int, etag: str | None = None
    ) -> bytes:
        raise NotImplementedError

    async def put(
        self,
        bucket: Bucket,
        key: str,
        body: bytes,
        *,
        content_type: str,
        cache_control: str | None = None,
    ) -> None:
        raise NotImplementedError

    async def copy(self, bucket: Bucket, key: str, *, to: Bucket) -> bool:
        raise NotImplementedError

    async def delete(self, bucket: Bucket, key: str) -> None:
        raise NotImplementedError


def media(size: int, *, upload_id: str | None = None) -> MediaAsset:
    return MediaAsset.start(
        media_id=MediaId(new_id()),
        owner_id=UserId(new_id()),
        kind=MediaKind.VIDEO if upload_id else MediaKind.IMAGE,
        purpose=MediaPurpose.PORTFOLIO,
        mime_type="video/mp4" if upload_id else "image/jpeg",
        size_bytes=size,
        now=NOW,
        upload_id=upload_id,
    )


async def test_photo_gets_one_signed_put() -> None:
    plan = await upload_plan(FakeStorage(), media(2 * MB))

    assert (plan.multipart, plan.part_size) == (False, None)
    [part] = plan.parts
    assert part.part_number is None
    assert part.url.endswith(f"?size={2 * MB}")
    assert part.headers == {"Content-Type": "image/jpeg"}


async def test_video_gets_parts_with_signed_sizes() -> None:
    size = 3 * PART_SIZE + 5
    plan = await upload_plan(FakeStorage(), media(size, upload_id="u1"))

    assert (plan.multipart, plan.part_size) == (True, PART_SIZE)
    assert [p.part_number for p in plan.parts] == [1, 2, 3, 4]
    assert plan.parts[-1].url.endswith("part=4&size=5&upload=u1")
    assert part_count(size) == 4
    assert [part_size(size, n) for n in (1, 4)] == [PART_SIZE, 5]


async def test_only_requested_parts_are_resigned() -> None:
    plan = await upload_plan(FakeStorage(), media(3 * PART_SIZE, upload_id="u1"), [3, 1, 3])

    assert [p.part_number for p in plan.parts] == [1, 3]


@pytest.mark.parametrize("numbers", [[], [0], [4]], ids=["none", "zero", "past-last"])
async def test_part_numbers_outside_the_upload_are_refused(numbers: list[int]) -> None:
    with pytest.raises(DomainValidationError):
        await upload_plan(FakeStorage(), media(3 * PART_SIZE, upload_id="u1"), numbers)


def multipart_asset(size: int) -> MediaAsset:
    return MediaAsset.start(
        media_id=MediaId(new_id()),
        owner_id=UserId(new_id()),
        kind=MediaKind.VIDEO,
        purpose=MediaPurpose.PORTFOLIO,
        mime_type="video/mp4",
        size_bytes=size,
        now=NOW,
        upload_id="u-1",
    )


def parts(*numbers: int) -> tuple[UploadedPart, ...]:
    return tuple(UploadedPart(part_number=n, etag=f"e{n}") for n in numbers)


def test_complete_accepts_exactly_the_planned_parts() -> None:
    ensure_all_parts(multipart_asset(2 * PART_SIZE + 1), parts(3, 1, 2))


def test_missing_parts_are_named_so_the_client_uploads_only_them() -> None:
    with pytest.raises(UploadIncompleteError) as caught:
        ensure_all_parts(multipart_asset(3 * PART_SIZE), parts(2))

    assert caught.value.params["missing_parts"] == [1, 3]


@pytest.mark.parametrize("numbers", [(1, 1, 2), (1, 2, 3)], ids=["repeated", "beyond-plan"])
def test_parts_outside_the_plan_are_rejected(numbers: tuple[int, ...]) -> None:
    with pytest.raises(DomainValidationError):
        ensure_all_parts(multipart_asset(2 * PART_SIZE), parts(*numbers))
