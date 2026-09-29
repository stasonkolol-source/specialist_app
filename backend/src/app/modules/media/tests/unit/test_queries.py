"""Адреса вариантов (ARCHITECTURE §10.4): CDN с неизменяемыми ключами, без CDN — presigned GET."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.media.application.config import VARIANT_URL_TTL, MediaConfig
from app.modules.media.application.queries import MediaQueries
from app.modules.media.domain.asset import MediaAsset
from app.modules.media.domain.policy import MediaKind, MediaPurpose
from app.platform.kernel.ids import MediaId, UserId, new_id
from app.platform.storage.port import GET_TTL, Bucket

pytestmark = pytest.mark.unit


def asset(purpose: MediaPurpose) -> MediaAsset:
    return MediaAsset.start(
        media_id=MediaId(new_id()),
        owner_id=UserId(new_id()),
        kind=MediaKind.IMAGE,
        purpose=purpose,
        mime_type="image/jpeg",
        size_bytes=1,
        now=datetime(2026, 10, 5, tzinfo=UTC),
    )


class NoAssets:
    async def asset(self, owner_id: UserId, media_id: MediaId) -> MediaAsset | None:
        return None

    async def asset_by_id(self, media_id: MediaId) -> MediaAsset | None:
        return None


class Signer:
    def __init__(self) -> None:
        self.signed: list[tuple[Bucket, str, timedelta]] = []

    async def presign_get(self, bucket: Bucket, key: str, *, ttl: timedelta = GET_TTL) -> str:
        self.signed.append((bucket, key, ttl))
        return f"https://s3.test/{bucket}/{key}?signed"


def queries(signer: Signer, cdn: str | None) -> MediaQueries:
    return MediaQueries(NoAssets(), signer, MediaConfig(public_base_url=cdn))  # type: ignore[arg-type]


async def test_variants_come_from_the_cdn_when_there_is_one() -> None:
    signer = Signer()

    url = await queries(signer, "https://cdn.sosedi.test/").variant_url(
        asset(MediaPurpose.PORTFOLIO), "m/1/lg.webp"
    )

    assert url == "https://cdn.sosedi.test/m/1/lg.webp"
    assert signer.signed == []


async def test_without_cdn_variants_are_signed_for_an_hour() -> None:
    signer = Signer()

    url = await queries(signer, None).variant_url(asset(MediaPurpose.JOB), "m/1/lg.webp")

    assert url == "https://s3.test/media/m/1/lg.webp?signed"
    assert signer.signed == [(Bucket.MEDIA, "m/1/lg.webp", VARIANT_URL_TTL)]


async def test_private_purposes_are_signed_briefly_even_with_a_cdn() -> None:
    # сообщения, отзывы, документы (v1): варианты в private — только по короткой подписи
    signer = Signer()

    url = await queries(signer, "https://cdn.sosedi.test").variant_url(
        asset(MediaPurpose.MESSAGE), "m/1/lg.webp"
    )

    assert url == "https://s3.test/private/m/1/lg.webp?signed"
    assert signer.signed == [(Bucket.PRIVATE, "m/1/lg.webp", GET_TTL)]
