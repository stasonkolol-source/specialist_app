"""Проверка фото omni-moderation (DEVELOPMENT_PLAN 6.7, ARCHITECTURE §10.3, ADR-0016 §4).

Фото обработано по-настоящему (дочерний процесс Pillow), хранилище — в памяти, провайдер —
фейк с заданным ответом, задачи — как в воркере. Флаг — кейс P2 о файле, фото видно; P0 — фото
скрыто сразу (API без вариантов, варианты — в private) и кейс P0, а одобрение модератора
возвращает его; чистое — `approved` без кейса, повтор провайдера не зовёт.
Данные коммитятся: у каждого теста свои пользователи.
"""

import io
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from dishka import AsyncContainer
from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._wiring import make_worker_container
from app.modules.media.api import MediaApi
from app.modules.media.application.facade import MediaFacade
from app.modules.media.application.ports import (
    ImageProcessor,
    MediaQuery,
    MediaRepository,
    VideoProcessor,
)
from app.modules.media.application.queries import MediaQueries
from app.modules.media.application.use_cases.hide_variants import (
    HideVariants,
    HideVariantsCommand,
    RestoreVariants,
)
from app.modules.media.application.use_cases.process_media import (
    ProcessMedia,
    ProcessMediaCommand,
)
from app.modules.moderation.application.ports import AutoCheckMetrics
from app.modules.moderation.application.use_cases.check_image import (
    CheckImage,
    CheckImageCommand,
)
from app.modules.moderation.application.use_cases.decide_case import (
    DecideCase,
    DecideCaseCommand,
)
from app.modules.moderation.application.use_cases.open_case import CaseOpener
from app.modules.moderation.domain.images import ImageAction
from app.platform.ai.port import ModerationResult, Unavailable
from app.platform.audit.port import AuditLog
from app.platform.contracts.events.moderation import ModerationDecision
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import MediaId, UserId, new_id
from app.platform.queue.port import JobQueue
from app.platform.settings import Settings
from app.platform.storage.port import Bucket, StoragePort
from tests.plugins.identity import insert_user

pytestmark = pytest.mark.integration

EXPLICIT = ModerationResult(flagged=True, scores={"sexual": 0.97, "violence": 0.1})
VIOLENCE = ModerationResult(flagged=True, scores={"violence": 0.86, "violence/graphic": 0.38})
CLEAN = ModerationResult(flagged=False, scores={"sexual": 0.001, "violence": 0.002})


class MemoryStorage:
    """StoragePort в памяти: обработка пишет варианты, проверка читает `md`, скрытие переносит."""

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

    async def copy(self, bucket: Bucket, key: str, *, to: Bucket) -> bool:
        body = self.objects.get((str(bucket), key))
        if body is None:
            return False
        self.objects[(str(to), key)] = body
        return True

    async def delete(self, bucket: Bucket, key: str) -> None:
        self.objects.pop((str(bucket), key), None)

    def keys(self, bucket: Bucket, media_id: MediaId) -> set[str]:
        return {k for b, k in self.objects if b == str(bucket) and str(media_id) in k}


class Provider:
    """omni-moderation: ответ задаёт тест; что ушло — `data:` URL."""

    def __init__(self, result: ModerationResult | Unavailable) -> None:
        self.result = result
        self.urls: list[str] = []

    async def check_text(self, text: str) -> ModerationResult | Unavailable:
        raise AssertionError("фото не проверяют текстом")

    async def check_image(self, url: str) -> ModerationResult | Unavailable:
        self.urls.append(url)
        return self.result


def photo() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (2000, 1500), (180, 90, 40)).save(out, "JPEG", quality=85)
    return out.getvalue()


@pytest.fixture
async def worker(storage_settings: Settings) -> AsyncIterator[AsyncContainer]:
    container = make_worker_container(storage_settings)
    try:
        yield container
    finally:
        await container.close()


class World:
    def __init__(self, container: AsyncContainer) -> None:
        self.container = container
        self.storage = MemoryStorage()

    async def photo(self, purpose: str = "portfolio") -> tuple[UserId, MediaId]:
        """Фото загружено (как после complete) и обработано: варианты — в бакете media."""
        async with self.container() as request:
            session = await request.get(AsyncSession)
            owner = await insert_user(session)
            await session.commit()
        media_id = MediaId(new_id())
        key = f"{purpose}/2026/10/{media_id}/original"
        body = photo()
        self.storage.objects[(str(Bucket.INCOMING), key)] = body
        await self.execute(
            "INSERT INTO media.assets (id, owner_id, kind, purpose, status, bucket, object_key,"
            " mime_type, size_bytes, uploaded_at) VALUES (:id, :owner, 'image', :purpose,"
            " 'uploaded', 'incoming', :key, 'image/jpeg', :size, now())",
            id=media_id,
            owner=owner,
            purpose=purpose,
            key=key,
            size=len(body),
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
        return owner, media_id

    async def check(
        self, owner: UserId, media_id: MediaId, provider: Provider, purpose: str = "portfolio"
    ) -> Any:
        """Подписчик MediaReady `moderation.check_image` — с фейком провайдера и памятью."""
        async with self.container() as request:
            check = CheckImage(
                await request.get(UnitOfWork),
                await self.facade(request),
                provider,
                await request.get(CaseOpener),
                await request.get(AutoCheckMetrics),
                await request.get(AuditLog),
            )
            return await check(
                CheckImageCommand(media_id=media_id, owner_id=owner, purpose=purpose)
            )

    async def facade(self, request: AsyncContainer) -> MediaFacade:
        return MediaFacade(
            await request.get(MediaQuery),
            await request.get(MediaQueries),
            await request.get(JobQueue),
            await request.get(MediaRepository),
            cast(StoragePort, self.storage),
        )

    async def run_media_task(self, name: str, media_id: MediaId) -> int:
        """Задачи `media.hide_variants` / `media.restore_variants` этого файла — с памятью."""
        engine = await self.container.get(AsyncEngine)
        async with engine.begin() as conn:
            count = (
                await conn.execute(
                    text(
                        "DELETE FROM procrastinate_jobs WHERE task_name = :name AND status = 'todo'"
                        " AND args->'payload'->>'media_id' = :id RETURNING id"
                    ),
                    {"name": name, "id": str(media_id)},
                )
            ).rowcount
        async with self.container() as request:
            uow, assets = await request.get(UnitOfWork), await request.get(MediaRepository)
            query, queue = await request.get(MediaQuery), await request.get(JobQueue)
            storage = cast(StoragePort, self.storage)
            run = (
                HideVariants(uow, assets, query, storage, queue, await request.get(Clock))
                if name == "media.hide_variants"
                else RestoreVariants(uow, assets, query, storage, queue)
            )
            for _ in range(count):
                await run(HideVariantsCommand(media_id=media_id))
        return count

    async def asset(self, media_id: MediaId) -> dict[str, Any]:
        return await self.row(
            "SELECT moderation_status, moderation_labels, hidden_at FROM media.assets"
            " WHERE id = :id",
            id=media_id,
        )

    async def cases(self, media_id: MediaId) -> list[dict[str, Any]]:
        engine = await self.container.get(AsyncEngine)
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT id, queue, subject_id, trigger, status, evidence, media_ids"
                    " FROM moderation.cases WHERE entity_type = 'media' AND entity_id = :id"
                ),
                {"id": media_id},
            )
            return [dict(row._mapping) for row in rows]

    async def shown(self, media_id: MediaId) -> tuple[str, int]:
        """Как фото видят другие модули (карточка S08/S10, кабинет S37): статус и варианты."""
        async with self.container() as request:
            media = await request.get(MediaApi)
            ref = (await media.refs([media_id]))[media_id]
            return ref.status, len(ref.variants)

    async def row(self, sql: str, **params: object) -> dict[str, Any]:
        engine = await self.container.get(AsyncEngine)
        async with engine.connect() as conn:
            return dict((await conn.execute(text(sql), params)).one()._mapping)

    async def execute(self, sql: str, **params: object) -> None:
        engine = await self.container.get(AsyncEngine)
        async with engine.begin() as conn:
            await conn.execute(text(sql), params)


async def test_flagged_photo_opens_p2_case_and_stays_visible(worker: AsyncContainer) -> None:
    world = World(worker)
    owner, media_id = await world.photo()
    variants = len(world.storage.keys(Bucket.MEDIA, media_id))
    assert variants == 3  # thumb, md, lg
    provider = Provider(VIOLENCE)

    verdict = await world.check(owner, media_id, provider)

    assert verdict.action is ImageAction.REVIEW
    [url] = provider.urls
    assert url.startswith("data:image/webp;base64,")  # сам вариант md, без ссылки на хранилище
    asset = await world.asset(media_id)
    assert asset["moderation_status"] == "flagged"
    assert asset["moderation_labels"] == {"violence": 0.86}
    [case] = await world.cases(media_id)
    assert (case["queue"], case["subject_id"], case["trigger"], case["status"]) == (
        "premod",
        owner,
        "auto_flag",
        "pending",
    )
    [evidence] = case["evidence"]
    assert evidence["signals"] == ["image:violence:0.86"]
    assert (evidence["purpose"], evidence["hidden"]) == ("portfolio", False)
    assert case["media_ids"] == [media_id]  # файл — под legal hold
    assert await world.shown(media_id) == ("ready", variants)  # до решения модератора фото видно

    # повтор задачи после commit: файл уже проверен — провайдер не зовётся, второго кейса нет
    assert await world.check(owner, media_id, provider) is None
    assert len(provider.urls) == 1
    assert len(await world.cases(media_id)) == 1


async def test_p0_photo_is_hidden_at_once_and_moderator_can_restore_it(
    worker: AsyncContainer,
) -> None:
    world = World(worker)
    owner, media_id = await world.photo("avatar")
    public = world.storage.keys(Bucket.MEDIA, media_id)
    assert len(public) == 3

    verdict = await world.check(owner, media_id, Provider(EXPLICIT), purpose="avatar")

    assert (verdict.action, verdict.reason_code) == (ImageAction.BLOCK, "sexual_content")
    assert (await world.asset(media_id))["moderation_status"] == "rejected"
    assert await world.shown(media_id) == ("rejected", 0)  # API его больше не показывает
    [case] = await world.cases(media_id)
    assert (case["queue"], case["status"]) == ("safety", "pending")
    [evidence] = case["evidence"]
    assert (evidence["hidden"], evidence["reason"]) == (True, "sexual_content")
    account = await world.row(
        "SELECT count(*) AS n FROM identity.restrictions WHERE user_id = :id", id=owner
    )
    assert account["n"] == 0  # аккаунт не заморожен: санкцию ставит модератор

    # варианты уходят из публичного бакета: по старой ссылке CDN фото не открыть
    assert await world.run_media_task("media.hide_variants", media_id) == 1
    assert world.storage.keys(Bucket.MEDIA, media_id) == set()
    assert world.storage.keys(Bucket.PRIVATE, media_id) == public
    assert (await world.asset(media_id))["hidden_at"] is not None

    # модератор: нарушения нет — фото возвращается
    async with worker() as request:
        decide = await request.get(DecideCase)
        await decide(DecideCaseCommand(case_id=case["id"], verdict=ModerationDecision.APPROVED))
    assert (await world.asset(media_id))["moderation_status"] == "approved"
    assert await world.run_media_task("media.restore_variants", media_id) == 1
    assert world.storage.keys(Bucket.MEDIA, media_id) == public
    assert world.storage.keys(Bucket.PRIVATE, media_id) == set()
    assert (await world.asset(media_id))["hidden_at"] is None
    assert await world.shown(media_id) == ("ready", 3)


async def test_clean_photo_is_approved_without_case(worker: AsyncContainer) -> None:
    world = World(worker)
    owner, media_id = await world.photo("job")

    verdict = await world.check(owner, media_id, Provider(CLEAN), purpose="job")

    assert verdict.action is ImageAction.CLEAN
    asset = await world.asset(media_id)
    assert (asset["moderation_status"], asset["moderation_labels"]) == ("approved", {})
    assert await world.cases(media_id) == []
    assert await world.shown(media_id) == ("ready", 3)
