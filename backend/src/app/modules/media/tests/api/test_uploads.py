"""Загрузка медиа по HTTP (DEVELOPMENT_PLAN 2.1, ARCHITECTURE §10.2).

«Готово, когда»: превышение квоты → 429; чужой media_id → 404; запрещённый MIME → 422;
presign → PUT → complete на Garage.
"""

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from tests.plugins.identity import insert_restriction

from app.modules.media.application.ports import MediaRepository
from app.modules.media.application.use_cases.cleanup_orphans import (
    CleanupOrphans,
    CleanupOrphansCommand,
)
from app.modules.media.domain.asset import MediaAsset
from app.modules.media.domain.policy import MB, MediaKind, MediaPurpose
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import MediaId, new_id
from app.platform.storage.port import PART_SIZE, Bucket, StoragePort

from .conftest import Media, put

pytestmark = pytest.mark.integration

JPEG = b"\xff\xd8\xff\xe0" + b"j" * 2044


async def test_photo_is_uploaded_and_queued_for_processing(media: Media) -> None:
    started = await media.start(size_bytes=len(JPEG))
    assert started.status_code == 201, started.text
    plan = started.json()
    assert (plan["multipart"], plan["part_size"]) == (False, None)
    [part] = plan["parts"]

    assert (await put(part, JPEG)).status_code == 200
    done = await media.complete(plan["media_id"])

    assert done.status_code == 200, done.text
    body = done.json()
    assert (body["status"], body["kind"], body["size_bytes"]) == ("uploaded", "image", len(JPEG))
    assert body["preview_url"]
    assert len(await media.jobs("media.process", plan["media_id"])) == 1
    again = await media.complete(plan["media_id"])  # ответ на первый мог потеряться
    assert (again.status_code, again.json()["status"]) == (200, "uploaded")
    assert len(await media.jobs("media.process", plan["media_id"])) == 1


@pytest.mark.parametrize("kind", ["suspended", "banned"])
async def test_suspended_or_banned_account_cannot_upload(media: Media, kind: str) -> None:
    async with media.app.container() as request:
        await insert_restriction(await request.get(AsyncSession), media.user_id, kind)

    response = await media.start()

    assert response.status_code == 403
    assert (response.json()["code"], response.json()["restriction"]) == ("restricted", kind)


async def test_posting_ban_does_not_stop_uploads(media: Media) -> None:
    async with media.app.container() as request:
        await insert_restriction(await request.get(AsyncSession), media.user_id, "posting_blocked")

    assert (await media.start()).status_code == 201  # публикацию проверит контентный модуль


async def test_video_over_50_mb_goes_in_parts(media: Media) -> None:
    size = 50 * MB + 1
    started = await media.start(mime_type="video/mp4", size_bytes=size)
    assert started.status_code == 201, started.text
    plan = started.json()
    assert (plan["multipart"], plan["part_size"]) == (True, PART_SIZE)
    assert len(plan["parts"]) == -(-size // PART_SIZE)

    etags = []
    for part in plan["parts"]:
        length = min(PART_SIZE, size - (part["part_number"] - 1) * PART_SIZE)
        response = await put(part, b"v" * length)
        assert response.status_code == 200, response.text
        etags.append({"part_number": part["part_number"], "etag": response.headers["etag"]})
    done = await media.complete(plan["media_id"], etags)

    assert done.status_code == 200, done.text
    assert (done.json()["status"], done.json()["size_bytes"]) == ("uploaded", size)


async def test_links_can_be_signed_again(media: Media) -> None:
    # само истечение ссылки проверяет tests/integration/test_storage.py
    plan = (await media.start(size_bytes=len(JPEG))).json()

    fresh = await media.app.client.post(
        f"/api/v1/media/uploads/{plan['media_id']}/parts", json={}, headers=media.headers
    )

    assert fresh.status_code == 200, fresh.text
    [part] = fresh.json()["parts"]
    assert (await put(part, JPEG)).status_code == 200
    assert (await media.complete(plan["media_id"])).status_code == 200
    after = await media.app.client.post(
        f"/api/v1/media/uploads/{plan['media_id']}/parts", json={}, headers=media.headers
    )
    assert (after.status_code, after.json()["code"]) == (409, "media_state_conflict")


async def test_complete_before_the_file_arrives_is_a_conflict(media: Media) -> None:
    plan = (await media.start()).json()

    early = await media.complete(plan["media_id"])

    assert (early.status_code, early.json()["code"]) == (409, "media_upload_incomplete")


@pytest.mark.authz
async def test_foreign_media_is_not_found(media: Media) -> None:
    plan = (await media.start()).json()
    stranger = await media.other_user()

    for response in (
        await stranger.get(plan["media_id"]),
        await stranger.parts(plan["media_id"]),
        await stranger.complete(plan["media_id"]),
        await stranger.delete(plan["media_id"]),
    ):
        assert (response.status_code, response.json()["code"]) == (404, "media_not_found")
    assert (await media.get(plan["media_id"])).status_code == 200


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"mime_type": "application/zip"}, "media_type_not_allowed"),
        ({"purpose": "job", "mime_type": "video/mp4"}, "media_type_not_allowed"),
        ({"purpose": "job", "size_bytes": 16 * MB}, "media_too_large"),
        ({"purpose": "message"}, "media_purpose_not_available"),
    ],
    ids=["zip", "video-to-job", "too-large", "messages-are-v1"],
)
async def test_refused_files_are_422(media: Media, body: dict[str, object], code: str) -> None:
    response = await media.start(**body)

    assert (response.status_code, response.json()["code"]) == (422, code)


async def test_too_large_answer_names_the_limit(media: Media) -> None:
    response = await media.start(purpose="job", size_bytes=16 * MB)

    assert response.json()["max_bytes"] == 15 * MB
    assert "15" in response.json()["detail"]


async def test_file_beyond_every_limit_is_too_large_not_invalid(media: Media) -> None:
    response = await media.start(mime_type="video/mp4", size_bytes=10**12)

    assert (response.status_code, response.json()["code"]) == (422, "media_too_large")
    assert response.json()["max_bytes"] == 200 * MB


async def test_type_refusal_says_what_fits_this_purpose(media: Media) -> None:
    response = await media.start(purpose="job", mime_type="video/mp4")

    assert response.json()["allowed"] == "JPEG, PNG, WebP, HEIC"
    assert "MP4" not in response.json()["detail"]


async def test_fifty_uploads_per_hour(media: Media) -> None:
    for _ in range(50):
        assert (await media.start()).status_code == 201

    over = await media.start()

    assert (over.status_code, over.json()["code"]) == (429, "rate_limited")
    assert int(over.headers["retry-after"]) > 0


async def test_refused_files_do_not_spend_the_daily_quota(media: Media) -> None:
    for _ in range(6):  # 6 × 200 MB — больше суточного гигабайта, но все отказы
        refused = await media.start(purpose="job", mime_type="video/mp4", size_bytes=200 * MB)
        assert refused.status_code == 422

    accepted = await media.start(mime_type="video/mp4", size_bytes=200 * MB)

    assert accepted.status_code == 201, accepted.text


async def test_one_gigabyte_per_day(media: Media) -> None:
    for _ in range(5):  # 5 × 200 MB = 1000 MB из 1024
        started = await media.start(mime_type="video/mp4", size_bytes=200 * MB)
        assert started.status_code == 201, started.text

    over = await media.start(mime_type="video/mp4", size_bytes=200 * MB)

    assert (over.status_code, over.json()["code"]) == (429, "rate_limited")


async def test_delete_hides_the_file_and_keeps_it_for_30_days(media: Media) -> None:
    plan = (await media.start(size_bytes=len(JPEG))).json()
    await put(plan["parts"][0], JPEG)
    await media.complete(plan["media_id"])

    assert (await media.delete(plan["media_id"])).status_code == 204
    assert (await media.get(plan["media_id"])).status_code == 404
    assert (await media.delete(plan["media_id"])).status_code == 404
    # объекты загруженного файла удаляет media.purge_deleted через 30 дней (шаг 2.2)
    assert await media.jobs("media.delete_objects", plan["media_id"]) == []
    assert await media.stored(plan["media_id"]) is not None


async def test_deleting_an_unfinished_upload_removes_its_object(media: Media) -> None:
    plan = (await media.start(size_bytes=len(JPEG))).json()
    await put(plan["parts"][0], JPEG)  # файл дошёл, а complete не было

    assert (await media.delete(plan["media_id"])).status_code == 204

    assert await media.run_jobs("media.delete_objects", plan["media_id"]) == 1
    assert await media.stored(plan["media_id"]) is None


async def test_deleting_an_unfinished_multipart_aborts_it(media: Media) -> None:
    plan = (await media.start(mime_type="video/mp4", size_bytes=50 * MB + 1)).json()

    assert (await media.delete(plan["media_id"])).status_code == 204

    [payload] = await media.jobs("media.delete_objects", plan["media_id"])
    assert payload["upload_id"]
    assert await media.run_jobs("media.delete_objects", plan["media_id"]) == 1
    # часть в 1 байт: на большую Garage рвёт соединение, не дочитав тело
    storage: StoragePort = await media.app.container.get(StoragePort)
    late = await storage.presign_part(
        Bucket.INCOMING,
        await media.object_key(plan["media_id"]),
        upload_id=payload["upload_id"],
        part_number=1,
        size=1,
    )
    response = await put({"url": late.url, "headers": dict(late.headers)}, b"v")
    assert response.status_code == 404  # NoSuchUpload: части больше некуда класть


async def test_complete_names_the_missing_parts(media: Media) -> None:
    size = 50 * MB + 1  # 7 частей по 8 MiB
    plan = (await media.start(mime_type="video/mp4", size_bytes=size)).json()
    parts = [{"part_number": n, "etag": f"e{n}"} for n in range(1, 7)]

    response = await media.complete(plan["media_id"], parts)

    assert (response.status_code, response.json()["code"]) == (409, "media_upload_incomplete")
    assert response.json()["missing_parts"] == [7]
    # загрузка не испорчена: недостающую часть можно подписать и догрузить
    assert (await media.parts(plan["media_id"], [7])).status_code == 200


async def test_file_other_than_declared_fails_and_is_removed(media: Media) -> None:
    plan = (await media.start(size_bytes=len(JPEG))).json()
    # объект другого размера по тому же ключу: подпись клиента такой PUT не пропустит,
    # но хранилище могло отдать чужой или испорченный объект
    storage: StoragePort = await media.app.container.get(StoragePort)
    other = await storage.presign_put(
        Bucket.INCOMING,
        await media.object_key(plan["media_id"]),
        content_type="image/jpeg",
        size=len(JPEG) - 1,
    )
    await put({"url": other.url, "headers": dict(other.headers)}, JPEG[:-1])

    response = await media.complete(plan["media_id"])

    assert (response.status_code, response.json()["code"]) == (422, "media_upload_mismatch")
    assert (await media.get(plan["media_id"])).json()["status"] == "failed"
    assert await media.run_jobs("media.delete_objects", plan["media_id"]) == 1
    assert await media.stored(plan["media_id"]) is None


async def test_long_multipart_upload_id_fits(media: Media) -> None:
    # у R2 id multipart-загрузки длиннее 255 символов
    async with media.app.container() as request:
        uow = await request.get(UnitOfWork)
        assets = await request.get(MediaRepository)
        clock = await request.get(Clock)
        asset = MediaAsset.start(
            media_id=MediaId(new_id()),
            owner_id=media.user_id,
            kind=MediaKind.VIDEO,
            purpose=MediaPurpose.PORTFOLIO,
            mime_type="video/mp4",
            size_bytes=60 * MB,
            now=clock.now(),
            upload_id="r2/" + "x" * 600,
        )
        async with uow:
            await assets.add(asset)

    response = await media.get(str(asset.id))

    assert response.status_code == 200, response.text


async def test_same_idempotency_key_starts_one_upload(media: Media) -> None:
    headers = media.headers | {"idempotency-key": "same-key-for-both"}
    body = {"purpose": "avatar", "mime_type": "image/png", "size_bytes": 100}

    first = await media.app.client.post("/api/v1/media/uploads", json=body, headers=headers)
    second = await media.app.client.post("/api/v1/media/uploads", json=body, headers=headers)

    assert first.status_code == second.status_code == 201
    assert first.json()["media_id"] == second.json()["media_id"]
    assert second.headers["idempotency-replayed"] == "true"


async def test_uploads_abandoned_for_a_day_fail(media: Media) -> None:
    plan = (await media.start()).json()
    engine = await media.app.container.get(AsyncEngine)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE media.assets SET created_at = now() - interval '25 hours' WHERE id = :id"),
            {"id": plan["media_id"]},
        )

    async with media.app.container() as request:
        cleanup = await request.get(CleanupOrphans)
        assert await cleanup(CleanupOrphansCommand(older_than=timedelta(hours=24))) >= 1

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT status, failure_reason FROM media.assets WHERE id = :id"),
                {"id": plan["media_id"]},
            )
        ).one()
    assert tuple(row) == ("failed", "abandoned")
    assert len(await media.jobs("media.delete_objects", plan["media_id"])) == 1
