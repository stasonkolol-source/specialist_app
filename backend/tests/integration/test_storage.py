"""StoragePort на Garage: presign → PUT → HEAD, multipart, ошибки (DEVELOPMENT_PLAN 0.24, 2.1)."""

import asyncio
from collections.abc import Iterator
from datetime import timedelta

import httpx
import pytest

from app.platform.kernel.clock import SystemClock
from app.platform.kernel.ids import new_id
from app.platform.settings import Settings
from app.platform.storage.port import Bucket, StorageRejectedError, UploadedPart
from app.platform.storage.s3 import S3Storage
from tests.plugins.containers import GarageInfo

pytestmark = pytest.mark.integration

JPEG = b"\xff\xd8\xff\xe0" + b"j" * 2048


@pytest.fixture
def s3_settings(
    settings: Settings, garage: GarageInfo, monkeypatch: pytest.MonkeyPatch
) -> Settings:
    """Настройки теста плюс S3 на Garage: после `settings`, который чистит окружение."""
    monkeypatch.setenv("S3_ENDPOINT_URL", garage.endpoint_url)
    monkeypatch.setenv("S3_REGION", "garage")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", garage.access_key_id)
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", garage.secret_access_key)
    return Settings(env_file=None)


@pytest.fixture
def storage(s3_settings: Settings) -> Iterator[S3Storage]:
    storage = S3Storage(s3_settings.s3, SystemClock())
    yield storage
    storage.close()


def key() -> str:
    return f"tests/{new_id()}.jpg"


async def test_presigned_put_then_head_reports_size_and_type(storage: S3Storage) -> None:
    name = key()
    signed = await storage.presign_put(
        Bucket.INCOMING, name, content_type="image/jpeg", size=len(JPEG)
    )

    async with httpx.AsyncClient() as client:
        put = await client.put(signed.url, content=JPEG, headers=dict(signed.headers))
        stored = await storage.head(Bucket.INCOMING, name)
        got = await client.get(await storage.presign_get(Bucket.INCOMING, name))

    assert put.status_code == 200, put.text
    assert stored is not None
    assert (stored.size, stored.content_type) == (len(JPEG), "image/jpeg")
    assert stored.etag == put.headers["etag"].strip('"')
    assert got.content == JPEG


@pytest.mark.parametrize(
    ("body", "content_type"),
    [(JPEG + b"x", "image/jpeg"), (JPEG[:-1], "image/jpeg"), (JPEG, "image/png")],
    ids=["bigger", "smaller", "other-type"],
)
async def test_signature_locks_size_and_type(
    storage: S3Storage, body: bytes, content_type: str
) -> None:
    name = key()
    signed = await storage.presign_put(
        Bucket.INCOMING, name, content_type="image/jpeg", size=len(JPEG)
    )

    async with httpx.AsyncClient() as client:
        put = await client.put(signed.url, content=body, headers={"Content-Type": content_type})

    assert put.status_code == 403
    assert await storage.head(Bucket.INCOMING, name) is None


async def test_expired_link_is_rejected(storage: S3Storage) -> None:
    signed = await storage.presign_put(
        Bucket.INCOMING, key(), content_type="image/jpeg", size=len(JPEG), ttl=timedelta(seconds=1)
    )
    await asyncio.sleep(2)

    async with httpx.AsyncClient() as client:
        put = await client.put(signed.url, content=JPEG, headers=dict(signed.headers))

    # Garage — 400, R2 — 403: клиент в обоих случаях просит новую ссылку
    assert put.status_code in {400, 403}


async def test_multipart_upload_assembles_parts(storage: S3Storage) -> None:
    name = f"tests/{new_id()}.mp4"
    chunks = [b"a" * (5 * 1024 * 1024), b"b" * 1024]
    upload_id = await storage.start_multipart(Bucket.INCOMING, name, content_type="video/mp4")

    parts: list[UploadedPart] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for number, chunk in reversed(list(enumerate(chunks, start=1))):  # порядок не важен
            signed = await storage.presign_part(
                Bucket.INCOMING, name, upload_id=upload_id, part_number=number, size=len(chunk)
            )
            put = await client.put(signed.url, content=chunk)
            assert put.status_code == 200, put.text
            parts.append(UploadedPart(part_number=number, etag=put.headers["etag"]))
    await storage.complete_multipart(Bucket.INCOMING, name, upload_id=upload_id, parts=parts)

    stored = await storage.head(Bucket.INCOMING, name)
    assert stored is not None
    assert (stored.size, stored.content_type) == (sum(map(len, chunks)), "video/mp4")


async def test_repeated_complete_after_lost_response_is_accepted(storage: S3Storage) -> None:
    name = f"tests/{new_id()}.mp4"
    upload_id = await storage.start_multipart(Bucket.INCOMING, name, content_type="video/mp4")
    signed = await storage.presign_part(
        Bucket.INCOMING, name, upload_id=upload_id, part_number=1, size=len(JPEG)
    )
    async with httpx.AsyncClient() as client:
        put = await client.put(signed.url, content=JPEG)
    parts = [UploadedPart(part_number=1, etag=put.headers["etag"])]
    await storage.complete_multipart(Bucket.INCOMING, name, upload_id=upload_id, parts=parts)

    # ответ на первый complete потерян — клиент повторяет тот же запрос
    await storage.complete_multipart(Bucket.INCOMING, name, upload_id=upload_id, parts=parts)

    stored = await storage.head(Bucket.INCOMING, name)
    assert stored is not None
    assert stored.size == len(JPEG)


async def test_complete_of_unknown_upload_still_fails(storage: S3Storage) -> None:
    name = f"tests/{new_id()}.mp4"
    upload_id = await storage.start_multipart(Bucket.INCOMING, name, content_type="video/mp4")
    await storage.abort_multipart(Bucket.INCOMING, name, upload_id=upload_id)

    with pytest.raises(StorageRejectedError):
        await storage.complete_multipart(
            Bucket.INCOMING,
            name,
            upload_id=upload_id,
            parts=[UploadedPart(part_number=1, etag="x")],
        )


async def test_aborted_multipart_leaves_nothing(storage: S3Storage) -> None:
    name = f"tests/{new_id()}.mp4"
    upload_id = await storage.start_multipart(Bucket.INCOMING, name, content_type="video/mp4")

    await storage.abort_multipart(Bucket.INCOMING, name, upload_id=upload_id)

    assert await storage.head(Bucket.INCOMING, name) is None
