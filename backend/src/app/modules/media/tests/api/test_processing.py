"""Обработка и раздача (DEVELOPMENT_PLAN 2.2, ARCHITECTURE §10.3–10.5) на Garage.

«Готово, когда»: фото → три WebP без EXIF; повтор задачи не плодит варианты;
decompression bomb → `rejected`. Задачи выполняются, как в воркере (run_task).
"""

import io
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from dishka import AsyncContainer
from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.modules.media.application.dto import ProcessedImage
from app.modules.media.application.ports import (
    ImageProcessor,
    MediaQuery,
    MediaRepository,
    ProcessingCrashedError,
)
from app.modules.media.application.use_cases.hide_variants import HideDeleted, HideDeletedCommand
from app.modules.media.application.use_cases.process_media import (
    ProcessMedia,
    ProcessMediaCommand,
)
from app.modules.media.application.use_cases.purge_deleted import (
    PurgeDeleted,
    PurgeDeletedCommand,
)
from app.modules.media.application.use_cases.retry_stuck import RetryStuck, RetryStuckCommand
from app.modules.media.domain.asset import MAX_ATTEMPTS
from app.modules.media.tests.images import exif, photo, png_header_only
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.errors import ExternalServiceError
from app.platform.kernel.ids import MediaId
from app.platform.queue.port import JobQueue
from app.platform.storage.port import Bucket, StoragePort, StorageRejectedError

from .conftest import Media, put

pytestmark = pytest.mark.integration


async def uploaded(media: Media, body: bytes, mime_type: str = "image/jpeg") -> str:
    """Загрузить файл, как Mini App: start → PUT → complete; вернуть media_id."""
    plan = (await media.start(mime_type=mime_type, size_bytes=len(body))).json()
    assert (await put(plan["parts"][0], body)).status_code == 200
    done = await media.complete(plan["media_id"])
    assert done.status_code == 200, done.text
    return str(plan["media_id"])


async def processed(media: Media, media_id: str) -> dict[str, Any]:
    assert await media.run_jobs("media.process", media_id) == 1
    response = await media.get(media_id)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def s3(media: Media) -> StoragePort:
    port: StoragePort = await media.app.container.get(StoragePort)
    return port


async def built(
    request: AsyncContainer, storage: StoragePort, images: ImageProcessor | None = None
) -> ProcessMedia:
    """ProcessMedia из контейнера, но со своим хранилищем (и обработчиком фото)."""
    processor: ImageProcessor = images or cast(ImageProcessor, await request.get(ImageProcessor))
    return ProcessMedia(
        await request.get(UnitOfWork),
        await request.get(MediaRepository),
        await request.get(MediaQuery),
        storage,
        processor,
        await request.get(JobQueue),
        await request.get(Clock),
    )


@asynccontextmanager
async def process_media(
    media: Media, before_put: Callable[[int], Awaitable[None]]
) -> AsyncIterator[ProcessMedia]:
    """Обработка, в которой перед n-й записью варианта что-то случается."""
    storage = await s3(media)

    class Watched:
        puts = 0

        def __getattr__(self, name: str) -> Any:
            return getattr(storage, name)

        async def put(self, *args: Any, **kwargs: Any) -> None:
            self.puts += 1
            await before_put(self.puts)
            await storage.put(*args, **kwargs)

    async with media.app.container() as request:
        yield await built(request, cast(StoragePort, Watched()))


async def test_photo_becomes_webp_variants_without_exif(media: Media) -> None:
    media_id = await uploaded(media, photo("JPEG", exif=exif()))

    body = await processed(media, media_id)

    assert (body["status"], body["width"], body["height"]) == ("ready", 1600, 1200)
    assert body["preview_url"] is None
    assert body["placeholder"]
    assert [(v["name"], v["width"], v["height"]) for v in body["variants"]] == [
        ("thumb", 320, 240),
        ("md", 800, 600),
        ("lg", 1600, 1200),
    ]
    async with httpx.AsyncClient() as client:
        for variant in body["variants"]:
            got = await client.get(variant["url"])
            assert got.status_code == 200
            image = Image.open(io.BytesIO(got.content))
            assert image.format == "WEBP"
            assert not image.getexif()
            assert "icc_profile" not in image.info
    # сырой оригинал с GPS больше не нужен
    assert await media.run_jobs("media.delete_objects", media_id) == 1
    assert await media.stored(media_id) is None


async def test_repeated_processing_changes_nothing(media: Media) -> None:
    media_id = await uploaded(media, photo("JPEG"))
    first = await processed(media, media_id)

    async with media.app.container() as request:
        process = await request.get(ProcessMedia)
        assert await process(ProcessMediaCommand(media_id=MediaId(UUID(media_id)))) is None

    again = (await media.get(media_id)).json()
    assert [v["name"] for v in again["variants"]] == [v["name"] for v in first["variants"]]


async def test_retry_after_a_crash_overwrites_the_same_variants(media: Media) -> None:
    media_id = await uploaded(media, photo("JPEG"))

    async def crash_on_second_put(count: int) -> None:
        if count == 2:
            raise ExternalServiceError(service="storage")

    async with process_media(media, crash_on_second_put) as process:  # первый вариант записан
        with pytest.raises(ExternalServiceError):
            await process(ProcessMediaCommand(media_id=MediaId(UUID(media_id))))
    assert (await media.get(media_id)).json()["status"] == "processing"

    body = await processed(media, media_id)  # повтор задачи

    assert body["status"] == "ready"
    assert await media.keys(Bucket.MEDIA, f"m/{media_id}/") == {
        f"m/{media_id}/{name}.webp" for name in ("thumb", "md", "lg")
    }


async def test_overlapping_run_keeps_the_ready_variants(media: Media) -> None:
    media_id = await uploaded(media, photo("JPEG"))

    async def other_run_finishes(count: int) -> None:
        if count == 3:  # пока этот запуск пишет варианты, соседний закончил
            await media.set_status(media_id, "ready")

    async with process_media(media, other_run_finishes) as process:
        assert await process(ProcessMediaCommand(media_id=MediaId(UUID(media_id)))) == "ready"

    assert await media.jobs("media.delete_objects", media_id) == []  # чужой итог не трогаем
    assert len(await media.keys(Bucket.MEDIA, f"m/{media_id}/")) == 3


async def test_photo_deleted_while_processing_loses_fresh_variants(media: Media) -> None:
    media_id = await uploaded(media, photo("JPEG"))

    async def user_deletes(count: int) -> None:
        if count == 3:
            assert (await media.delete(media_id)).status_code == 204

    async with process_media(media, user_deletes) as process:
        assert await process(ProcessMediaCommand(media_id=MediaId(UUID(media_id)))) == "deleted"

    await media.run_jobs("media.delete_objects", media_id)
    assert await media.keys(Bucket.MEDIA, f"m/{media_id}/") == set()


async def test_storage_refusal_not_about_the_file_is_retried(media: Media) -> None:
    media_id = await uploaded(media, photo("JPEG"))
    storage = await s3(media)

    class DeniedStorage:
        def __getattr__(self, name: str) -> Any:
            return getattr(storage, name)

        async def get(self, *_: object, **__: object) -> bytes:
            raise StorageRejectedError("AccessDenied")  # ключи сменили — файл ни при чём

    async with media.app.container() as request:
        process = await built(request, cast(StoragePort, DeniedStorage()))
        with pytest.raises(ExternalServiceError):
            await process(ProcessMediaCommand(media_id=MediaId(UUID(media_id))))

    assert (await media.get(media_id)).json()["status"] == "processing"
    assert await media.jobs("media.delete_objects", media_id) == []  # оригинал цел


@pytest.mark.parametrize(
    ("body", "mime_type", "reason"),
    [
        (b"%PDF-1.7\n" + b"x" * 2000, "image/jpeg", "unsupported"),
        (png_header_only(20_000, 20_000), "image/png", "too_many_pixels"),
    ],
    ids=["pdf-as-jpeg", "decompression-bomb"],
)
async def test_bad_files_are_rejected(
    media: Media, body: bytes, mime_type: str, reason: str
) -> None:
    media_id = await uploaded(media, body, mime_type)

    result = await processed(media, media_id)

    assert (result["status"], result["failure_reason"]) == ("rejected", reason)
    assert result["variants"] == []
    # одна задача: оригинал и возможные остатки вариантов от прерванных запусков
    assert await media.run_jobs("media.delete_objects", media_id) == 1
    assert await media.stored(media_id) is None


async def test_file_replaced_after_complete_is_rejected(media: Media) -> None:
    original = photo("JPEG")
    media_id = await uploaded(media, original)
    # тот же размер и тип, другое содержимое: presigned PUT ещё жив
    store = await s3(media)
    await store.put(
        Bucket.INCOMING,
        await media.object_key(media_id),
        bytes(reversed(original)),
        content_type="image/jpeg",
    )

    result = await processed(media, media_id)

    assert (result["status"], result["failure_reason"]) == ("rejected", "mismatch")


async def test_deleted_photo_is_hidden_at_once(media: Media) -> None:
    media_id = await uploaded(media, photo("JPEG"))
    await processed(media, media_id)

    assert (await media.delete(media_id)).status_code == 204
    assert await media.run_jobs("media.hide_variants", media_id) == 1

    # по старой публичной ссылке варианта больше нет; копия ждёт очистки в private
    assert await media.keys(Bucket.MEDIA, f"m/{media_id}/") == set()
    assert len(await media.keys(Bucket.PRIVATE, f"m/{media_id}/")) == 3


async def test_deleted_photo_is_purged_after_30_days(media: Media) -> None:
    media_id = await uploaded(media, photo("JPEG"))
    await processed(media, media_id)
    assert (await media.delete(media_id)).status_code == 204
    await media.run_jobs("media.hide_variants", media_id)
    engine = await media.app.container.get(AsyncEngine)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE media.assets SET deleted_at = now() - interval '31 days' WHERE id = :id"),
            {"id": media_id},
        )

    async with media.app.container() as request:
        purge = await request.get(PurgeDeleted)
        assert await purge(PurgeDeletedCommand()) >= 1

    # оригинал после обработки + очистка (оригинал и варианты в обоих бакетах) — одной задачей
    assert await media.run_jobs("media.delete_objects", media_id) == 2
    for bucket in (Bucket.MEDIA, Bucket.PRIVATE):
        assert await media.keys(bucket, f"m/{media_id}/") == set()
    async with engine.connect() as conn:
        purged: bool = (
            await conn.execute(
                text("SELECT purged_at IS NOT NULL FROM media.assets WHERE id = :id"),
                {"id": media_id},
            )
        ).scalar_one()
    assert purged is True


async def test_stuck_processing_is_retried(media: Media) -> None:
    media_id = await uploaded(media, photo("JPEG"))
    assert await media.lose_jobs("media.process", media_id) == 1  # задача потерялась
    engine = await media.app.container.get(AsyncEngine)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE media.assets SET status = 'processing',"
                " uploaded_at = now() - interval '20 minutes' WHERE id = :id"
            ),
            {"id": media_id},
        )

    async with media.app.container() as request:
        retry = await request.get(RetryStuck)
        assert await retry(RetryStuckCommand()) >= 1

    assert (await processed(media, media_id))["status"] == "ready"


async def test_crash_not_caused_by_the_file_is_retried_then_gives_up(media: Media) -> None:
    media_id = await uploaded(media, photo("JPEG"))

    class Crashing:
        async def process(self, data: bytes) -> ProcessedImage:
            raise ProcessingCrashedError("worker restarted")  # рестарт стенда, OOM-kill

    for _attempt in range(MAX_ATTEMPTS - 1):  # повтор: файл ни при чём, оригинал цел
        async with media.app.container() as request:
            process = await built(request, await s3(media), Crashing())
            with pytest.raises(ProcessingCrashedError):
                await process(ProcessMediaCommand(media_id=MediaId(UUID(media_id))))
        assert (await media.get(media_id)).json()["status"] == "processing"
        assert await media.jobs("media.delete_objects", media_id) == []

    async with media.app.container() as request:  # последняя попытка — честный отказ
        process = await built(request, await s3(media), Crashing())
        assert await process(ProcessMediaCommand(media_id=MediaId(UUID(media_id)))) == "rejected"
    assert (await media.get(media_id)).json()["failure_reason"] == "unreadable"


async def test_photo_stuck_for_a_day_is_rejected(media: Media) -> None:
    media_id = await uploaded(media, photo("JPEG"))
    assert await media.lose_jobs("media.process", media_id) == 1
    engine = await media.app.container.get(AsyncEngine)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE media.assets SET status = 'processing',"
                " uploaded_at = now() - interval '2 days' WHERE id = :id"
            ),
            {"id": media_id},
        )

    async with media.app.container() as request:
        retry = await request.get(RetryStuck)
        await retry(RetryStuckCommand())

    body = (await media.get(media_id)).json()
    assert (body["status"], body["failure_reason"]) == ("rejected", "unreadable")
    assert len(await media.jobs("media.delete_objects", media_id)) == 1


async def test_deleted_photo_stays_public_no_longer_than_the_safety_net(media: Media) -> None:
    media_id = await uploaded(media, photo("JPEG"))
    await processed(media, media_id)
    assert (await media.delete(media_id)).status_code == 204
    await media.run_jobs("media.hide_variants", media_id)  # «не прошла»: задача пропала
    engine = await media.app.container.get(AsyncEngine)
    async with engine.begin() as conn:  # вернуть как было: варианты публичны, hidden_at пуст
        await conn.execute(
            text(
                "UPDATE media.assets SET hidden_at = NULL,"
                " deleted_at = now() - interval '20 minutes' WHERE id = :id"
            ),
            {"id": media_id},
        )
    s3_store = await s3(media)
    for key in await media.keys(Bucket.PRIVATE, f"m/{media_id}/"):
        await s3_store.copy(Bucket.PRIVATE, key, to=Bucket.MEDIA)

    async with media.app.container() as request:
        hide = await request.get(HideDeleted)
        assert await hide(HideDeletedCommand()) >= 1
    assert await media.run_jobs("media.hide_variants", media_id) == 1

    assert await media.keys(Bucket.MEDIA, f"m/{media_id}/") == set()
