"""StoragePort на Garage и эндпоинты спайка 0.24: presign → PUT → HEAD (DEVELOPMENT_PLAN 0.24)."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import timedelta
from uuid import UUID

import httpx
import pytest
from botocore.exceptions import ClientError

from app.platform.kernel.clock import SystemClock
from app.platform.kernel.ids import new_id
from app.platform.settings import Settings
from app.platform.storage.port import PART_SIZE, Bucket, UploadedPart
from app.platform.storage.s3 import S3Storage
from tests.plugins.containers import GarageInfo
from tests.plugins.http import HttpApp, bearer, http_app

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


@pytest.fixture
async def web(s3_settings: Settings) -> AsyncIterator[HttpApp]:
    async with http_app(s3_settings) as app:
        yield app


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

    with pytest.raises(ClientError):
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


async def test_spike_endpoints_upload_small_file(web: HttpApp, settings: Settings) -> None:
    user_id = new_id()
    auth = bearer(settings, user_id)

    started = await web.client.post(
        "/api/v1/__spike/uploads",
        json={"filename": "IMG_0001.HEIC", "content_type": "", "size": len(JPEG)},
        headers=auth,
    )
    assert started.status_code == 201, started.text
    plan = started.json()
    assert plan["upload_id"] is None
    assert plan["key"].startswith(f"spike/{user_id}/")
    assert plan["key"].endswith(".heic")
    (part,) = plan["parts"]
    async with httpx.AsyncClient() as client:
        put = await client.put(part["url"], content=JPEG, headers=part["headers"])
    assert put.status_code == 200, put.text

    got = await web.client.get("/api/v1/__spike/uploads", params={"key": plan["key"]}, headers=auth)
    assert got.status_code == 200, got.text
    assert (got.json()["size"], got.json()["content_type"]) == (len(JPEG), "image/heic")


async def test_spike_endpoints_plan_multipart_for_big_file(
    web: HttpApp, settings: Settings
) -> None:
    size = PART_SIZE * 2 + 1
    started = await web.client.post(
        "/api/v1/__spike/uploads",
        json={"filename": "clip.mov", "content_type": "video/quicktime", "size": size},
        headers=bearer(settings),
    )

    assert started.status_code == 201, started.text
    plan = started.json()
    assert plan["upload_id"]
    assert [p["part_number"] for p in plan["parts"]] == [1, 2, 3]


async def test_spike_endpoints_hide_other_users_keys(web: HttpApp, settings: Settings) -> None:
    foreign = f"spike/{UUID(int=1)}/x.jpg"

    got = await web.client.get(
        "/api/v1/__spike/uploads", params={"key": foreign}, headers=bearer(settings)
    )

    assert got.status_code == 403


async def test_spike_endpoints_exist_only_in_dev(
    s3_settings: Settings, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    async with http_app(Settings(env_file=None)) as app:
        got = await app.client.get(
            "/api/v1/__spike/uploads", params={"key": "x"}, headers=bearer(settings)
        )

    assert got.status_code == 404
