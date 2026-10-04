"""Дубликаты фото портфолио (DEVELOPMENT_PLAN 7.6, ADR-0016 L6): обработка фото считает pHash,
по MediaReady модерация ищет такое же фото в портфолио других аккаунтов.

Два аккаунта загрузили одно фото (второй — пересжатое и уменьшенное) — один кейс P2 о профиле
второго с обеими работами; повтор задачи кейс не дублирует. Один аккаунт дважды — кейса нет.
Обработка — настоящая (дочерний процесс Pillow), хранилище — в памяти, задачи — как в воркере.
Данные коммитятся: у каждого теста свои пользователи.
"""

import io
import random
from collections.abc import AsyncIterator
from typing import Any, cast
from uuid import UUID

import pytest
from dishka import AsyncContainer
from PIL import Image, ImageDraw
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._wiring import make_worker_container
from app.modules.media.application.ports import (
    ImageProcessor,
    MediaQuery,
    MediaRepository,
    VideoProcessor,
)
from app.modules.media.application.use_cases.process_media import (
    ProcessMedia,
    ProcessMediaCommand,
)
from app.modules.moderation.application.use_cases.check_duplicates import (
    CheckDuplicates,
    CheckDuplicatesCommand,
)
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import MediaId, UserId, new_id
from app.platform.queue.port import JobQueue
from app.platform.settings import Settings
from app.platform.storage.port import Bucket, StoragePort
from tests.plugins.identity import insert_user
from tests.plugins.queue import run_queued

pytestmark = pytest.mark.integration

CHECK = "moderation.check_duplicates"


class MemoryStorage:
    """StoragePort в памяти — ровно то, что нужно обработке фото: прочитать и записать."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    async def get(
        self, bucket: Bucket, key: str, *, max_bytes: int, etag: str | None = None
    ) -> bytes:
        return self.objects[(str(bucket), key)]

    async def put(
        self,
        bucket: Bucket,
        key: str,
        body: bytes,
        *,
        content_type: str,
        cache_control: str | None = None,
    ) -> None:
        self.objects[(str(bucket), key)] = body


def photo(seed: int, size: tuple[int, int] = (1600, 1200), quality: int = 90) -> bytes:
    """Снимок с фигурами по seed; `size` и `quality` — та же картинка, уменьшенная и
    пересжатая (так копию выкладывают из чужого портфолио)."""
    rng = random.Random(seed)  # noqa: S311 — картинка для теста, не секрет
    image = Image.new("RGB", (1600, 1200), (rng.randrange(256), 90, rng.randrange(256)))
    draw = ImageDraw.Draw(image)
    for _ in range(25):
        x, y = rng.randrange(1600), rng.randrange(1200)
        w, h = rng.randrange(50, 600), rng.randrange(50, 600)
        draw.ellipse((x, y, x + w, y + h), fill=(rng.randrange(256), 0, rng.randrange(256)))
    image = image.resize(size, Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=quality)
    return out.getvalue()


@pytest.fixture
async def worker(storage_settings: Settings, geo_seeded: None) -> AsyncIterator[AsyncContainer]:
    container = make_worker_container(storage_settings)
    try:
        yield container
    finally:
        await container.close()


class World:
    def __init__(self, container: AsyncContainer) -> None:
        self.container = container
        self.storage = MemoryStorage()

    async def specialist(self) -> tuple[UserId, UUID]:
        """Пользователь с опубликованным профилем — строкой: модерация профиля не нужна."""
        async with self.container() as request:
            session = await request.get(AsyncSession)
            user_id = await insert_user(session)
            await session.commit()
        profile_id = new_id()
        await self.execute(
            "INSERT INTO specialists.profiles (id, user_id, kind, status, display_name, city_id,"
            " created_at, published_at, version) SELECT :id, :user, 'pro', 'published', 'Ana',"
            " c.id, now(), now(), 1 FROM geo.cities c WHERE c.slug = 'novi-sad'",
            id=profile_id,
            user=user_id,
        )
        return user_id, profile_id

    async def work(self, owner: UserId, profile_id: UUID, body: bytes) -> MediaId:
        """Фото загружено (как после complete), прикреплено работой и обработано."""
        media_id = MediaId(new_id())
        key = f"portfolio/2026/10/{media_id}/original"
        self.storage.objects[(str(Bucket.INCOMING), key)] = body
        await self.execute(
            "INSERT INTO media.assets (id, owner_id, kind, purpose, status, bucket, object_key,"
            " mime_type, size_bytes, uploaded_at) VALUES (:id, :owner, 'image', 'portfolio',"
            " 'uploaded', 'incoming', :key, 'image/jpeg', :size, now())",
            id=media_id,
            owner=owner,
            key=key,
            size=len(body),
        )
        item_id = new_id()
        await self.execute(
            "INSERT INTO specialists.portfolio_items (id, profile_id, status) VALUES"
            " (:id, :profile, 'published')",
            id=item_id,
            profile=profile_id,
        )
        await self.execute(
            "INSERT INTO specialists.portfolio_media (item_id, media_id, kind) VALUES"
            " (:item, :media, 'image')",
            item=item_id,
            media=media_id,
        )
        async with self.container() as request:
            process = ProcessMedia(
                await request.get(UnitOfWork),
                await request.get(MediaRepository),
                await request.get(MediaQuery),
                cast(StoragePort, self.storage),
                cast(ImageProcessor, await request.get(ImageProcessor)),
                cast(VideoProcessor, await request.get(VideoProcessor)),
                await request.get(JobQueue),
                await request.get(Clock),
            )
            assert str(await process(ProcessMediaCommand(media_id=media_id))) == "ready"
        return media_id

    async def check(self, owner: UserId) -> int:
        """Подписчик MediaReady файлов владельца — как воркер."""
        return await run_queued(self.container, CHECK, user_id=owner, by="owner_id")

    async def cases(self, profile_id: UUID) -> list[dict[str, Any]]:
        engine = await self.container.get(AsyncEngine)
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT queue, subject_id, trigger, status, evidence, media_ids"
                    " FROM moderation.cases WHERE entity_type = 'profile' AND entity_id = :id"
                ),
                {"id": profile_id},
            )
            return [dict(row._mapping) for row in rows]

    async def execute(self, sql: str, **params: object) -> None:
        engine = await self.container.get(AsyncEngine)
        async with engine.begin() as conn:
            await conn.execute(text(sql), params)

    async def scalar(self, sql: str, **params: object) -> Any:
        engine = await self.container.get(AsyncEngine)
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).scalar()


async def test_same_photo_in_two_accounts_opens_one_case(worker: AsyncContainer) -> None:
    world = World(worker)
    first, first_profile = await world.specialist()
    second, second_profile = await world.specialist()
    seed = new_id().int  # фото этого теста не совпадёт с фото соседних тестов

    original = await world.work(first, first_profile, photo(seed))
    assert await world.check(first) == 1
    assert await world.cases(first_profile) == []  # сравнивать было не с чем

    # второй выкладывает то же фото — пересжатое и уменьшенное
    copy = await world.work(second, second_profile, photo(seed, (1200, 900), quality=60))
    stored = await world.scalar("SELECT phash FROM media.assets WHERE id = :id", id=copy)
    assert stored is not None
    assert len(str(stored)) == 64
    assert await world.check(second) == 1

    [case] = await world.cases(second_profile)
    assert (case["queue"], case["subject_id"], case["trigger"], case["status"]) == (
        "premod",
        second,
        "auto_flag",
        "pending",
    )
    [evidence] = case["evidence"]
    assert evidence["signals"] == ["portfolio_duplicate"]
    assert evidence["media_id"] == str(copy)
    assert evidence["work_id"] is not None
    [match] = evidence["matches"]
    assert (match["media_id"], match["profile_id"]) == (str(original), str(first_profile))
    assert match["distance"] <= 8
    assert set(case["media_ids"]) == {copy, original}  # обе — под legal hold
    assert await world.cases(first_profile) == []  # автоматически никого не трогаем

    # повтор задачи (воркер упал после commit) — тот же кейс без второго повода
    async with worker() as request:
        check = await request.get(CheckDuplicates)
        await check(CheckDuplicatesCommand(media_id=copy, owner_id=second))
    [case] = await world.cases(second_profile)
    assert len(case["evidence"]) == 1


async def test_same_photo_twice_in_one_account_is_not_a_duplicate(
    worker: AsyncContainer,
) -> None:
    world = World(worker)
    owner, profile = await world.specialist()
    seed = new_id().int

    await world.work(owner, profile, photo(seed))
    await world.work(owner, profile, photo(seed, quality=70))

    assert await world.check(owner) == 2
    assert await world.cases(profile) == []
