"""Фото на проверку модерацией (6.7): вариант не прочитать — проверять нечего, но это видно в
журнале (только id и код хранилища), а фото подберёт `moderation.recheck_images`. Фото для
карточки кейса в чате модераторов (2.5b) — тот же вариант `md`, кроме скрытого."""

from dataclasses import replace
from typing import cast

import pytest
from structlog.testing import capture_logs

from app.modules.media.application.facade import MediaFacade
from app.modules.media.application.ports import MediaQuery, MediaRepository
from app.modules.media.application.queries import MediaQueries
from app.modules.media.domain.asset import MediaAsset, MediaStatus, ModerationStatus, Variant
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


class Stored:
    """Хранилище с вариантами: что и откуда прочитали."""

    def __init__(self) -> None:
        self.read: list[tuple[Bucket, str]] = []

    async def get(
        self, bucket: Bucket, key: str, *, max_bytes: int, etag: str | None = None
    ) -> bytes:
        self.read.append((bucket, key))
        return b"webp"


def ready(**changes: object) -> MediaAsset:
    media_id = MediaId(new_id())
    asset = MediaAsset.start(
        media_id=media_id,
        owner_id=UserId(new_id()),
        kind=MediaKind.IMAGE,
        purpose=MediaPurpose.PORTFOLIO,
        mime_type="image/jpeg",
        size_bytes=1000,
        now=FakeClock().now(),
    )
    variants = {"md": Variant(key=f"m/{media_id}/md.webp", width=800, height=600)}
    fields: dict[str, object] = {"status": MediaStatus.READY, "variants": variants, **changes}
    return replace(asset, **fields)  # type: ignore[arg-type]


def facade_for(asset: MediaAsset, storage: object) -> MediaFacade:
    return MediaFacade(
        cast(MediaQuery, Query(asset)),
        cast(MediaQueries, None),
        cast(JobQueue, None),
        cast(MediaRepository, None),
        cast(StoragePort, storage),
    )


async def test_card_photo_is_the_md_variant_even_after_the_check() -> None:
    """Карточка кейса в чате модераторов (2.5b): фото с флагом проверки — тот же вариант `md`."""
    asset = ready(moderation_status=ModerationStatus.FLAGGED)
    storage = Stored()

    image = await facade_for(asset, storage).image_for_card(asset.id)

    assert image is not None
    assert (image.body, image.content_type) == (b"webp", "image/webp")
    assert storage.read == [(Bucket("media"), f"m/{asset.id}/md.webp")]


@pytest.mark.parametrize(
    "changes",
    [
        {"moderation_status": ModerationStatus.REJECTED},
        {"hidden_at": FakeClock().now()},
        {"status": MediaStatus.PROCESSING},
    ],
    ids=["rejected", "hidden", "not_ready"],
)
async def test_hidden_or_unready_photo_is_not_sent(changes: dict[str, object]) -> None:
    asset = ready(**changes)
    storage = Stored()

    assert await facade_for(asset, storage).image_for_card(asset.id) is None
    assert storage.read == []  # скрытое (P0) в чат не уходит: не читаем вовсе
