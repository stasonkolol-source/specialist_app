"""Фото на проверку модерацией (6.7): вариант не прочитать — проверять нечего, но это видно в
журнале (только id и код хранилища), а фото подберёт `moderation.recheck_images`."""

from dataclasses import replace
from typing import cast

import pytest
from structlog.testing import capture_logs

from app.modules.media.application.facade import MediaFacade
from app.modules.media.application.ports import MediaQuery, MediaRepository
from app.modules.media.application.queries import MediaQueries
from app.modules.media.domain.asset import MediaAsset, MediaStatus, Variant
from app.modules.media.domain.policy import MediaKind, MediaPurpose
from app.platform.kernel.ids import MediaId, UserId, new_id
from app.platform.queue.port import JobQueue
from app.platform.storage.port import Bucket, StoragePort, StorageRejectedError
from app.platform.testing.clock import FakeClock

pytestmark = pytest.mark.unit


class Query:
    def __init__(self, asset: MediaAsset) -> None:
        self.asset = asset

    async def asset_by_id(self, media_id: MediaId) -> MediaAsset | None:
        return self.asset


class MissingVariant:
    async def get(
        self, bucket: Bucket, key: str, *, max_bytes: int, etag: str | None = None
    ) -> bytes:
        raise StorageRejectedError("NoSuchKey")


async def test_unreadable_variant_is_logged_by_id_only() -> None:
    now = FakeClock().now()
    media_id = MediaId(new_id())
    asset = replace(
        MediaAsset.start(
            media_id=media_id,
            owner_id=UserId(new_id()),
            kind=MediaKind.IMAGE,
            purpose=MediaPurpose.PORTFOLIO,
            mime_type="image/jpeg",
            size_bytes=1000,
            now=now,
        ),
        status=MediaStatus.READY,
        variants={"md": Variant(key=f"m/{media_id}/md.webp", width=800, height=600)},
    )
    facade = MediaFacade(
        cast(MediaQuery, Query(asset)),
        cast(MediaQueries, None),
        cast(JobQueue, None),
        cast(MediaRepository, None),
        cast(StoragePort, MissingVariant()),
    )

    with capture_logs() as logs:
        assert await facade.image_for_check(media_id) is None

    assert logs == [
        {
            "event": "media_check_variant_unreadable",
            "log_level": "warning",
            "media_id": str(media_id),
            "code": "NoSuchKey",
        }
    ]
