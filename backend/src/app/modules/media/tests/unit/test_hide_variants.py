"""Скрытие и возврат вариантов (6.7): решение меняется, пока объекты переносятся, — последнее
побеждает, и публичных вариантов у удалённого или отклонённого файла не остаётся."""

import copy
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Self, cast

import pytest

from app.modules.media.api import ModerationVerdict
from app.modules.media.application.facade import record_verdict
from app.modules.media.application.ports import MediaQuery, MediaRepository
from app.modules.media.application.use_cases.delete_media import DeleteMedia, DeleteMediaCommand
from app.modules.media.application.use_cases.hide_variants import (
    HideVariants,
    HideVariantsCommand,
    RestoreVariants,
)
from app.modules.media.domain.asset import (
    MediaAsset,
    MediaStatus,
    ModerationStatus,
    Variant,
    VariantName,
)
from app.modules.media.domain.policy import MediaKind, MediaPurpose
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import MediaId, UserId, new_id
from app.platform.queue.port import JobQueue
from app.platform.storage.port import Bucket, StoragePort
from app.platform.testing.clock import FakeClock

pytestmark = pytest.mark.unit

T1 = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)


class Transactions:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class Assets:
    """Репозиторий и чтение без блокировки на одной записи."""

    def __init__(self, asset: MediaAsset) -> None:
        self.asset = asset

    async def get_by_id_for_update(self, media_id: MediaId) -> MediaAsset:
        return self.asset

    async def get_for_update(self, owner_id: UserId, media_id: MediaId) -> MediaAsset:
        return self.asset

    async def save(self, asset: MediaAsset) -> None:
        self.asset = asset

    async def asset_by_id(self, media_id: MediaId) -> MediaAsset | None:
        return copy.deepcopy(self.asset)


class Jobs:
    def __init__(self) -> None:
        self.names: list[str] = []

    async def enqueue(self, task: Any, payload: Any, **kwargs: Any) -> None:
        self.names.append(task.name)

    def take(self, name: str) -> int:
        count = self.names.count(name)
        self.names = [n for n in self.names if n != name]
        return count


class Storage:
    """Два бакета; `before_copy` — что случится перед очередной копией (решение, удаление)."""

    def __init__(self, private: set[str]) -> None:
        self.buckets: dict[str, set[str]] = {"media": set(), "private": set(private)}
        self.before_copy: list[Callable[[], Awaitable[None]]] = []

    async def copy(self, bucket: Bucket, key: str, *, to: Bucket) -> bool:
        if self.before_copy:
            await self.before_copy.pop(0)()
        if key not in self.buckets[bucket.value]:
            return False
        self.buckets[to.value].add(key)
        return True

    async def delete(self, bucket: Bucket, key: str) -> None:
        self.buckets[bucket.value].discard(key)


def rejected_photo() -> MediaAsset:
    """Фото портфолио, скрытое при P0: варианты уже в private, `hidden_at` стоит."""
    media_id = MediaId(new_id())
    names = (VariantName.THUMB, VariantName.MD, VariantName.LG)
    return MediaAsset(
        id=media_id,
        owner_id=UserId(new_id()),
        kind=MediaKind.IMAGE,
        purpose=MediaPurpose.PORTFOLIO,
        status=MediaStatus.READY,
        bucket="incoming",
        object_key=f"portfolio/2026/10/{media_id}/original",
        mime_type="image/jpeg",
        size_bytes=1000,
        created_at=T1,
        moderation_status=ModerationStatus.REJECTED,
        hidden_at=T1,
        variants={n: Variant(key=f"m/{media_id}/{n}.webp", width=800, height=600) for n in names},
    )


class World:
    def __init__(self) -> None:
        self.assets = Assets(rejected_photo())
        self.jobs = Jobs()
        self.storage = Storage({v.key for v in self.asset.variants.values()})
        self.clock = FakeClock()
        self.keys = set(self.storage.buckets["private"])

    @property
    def asset(self) -> MediaAsset:
        return self.assets.asset

    @property
    def public(self) -> set[str]:
        return self.storage.buckets["media"]

    @property
    def private(self) -> set[str]:
        return self.storage.buckets["private"]

    async def decide(self, verdict: ModerationVerdict) -> None:
        repo = cast(MediaRepository, self.assets)
        await record_verdict(
            repo, cast(JobQueue, self.jobs), self.asset.id, verdict, labels=None, auto=False
        )

    async def delete(self) -> None:
        await DeleteMedia(
            cast(UnitOfWork, Transactions()),
            cast(MediaRepository, self.assets),
            cast(JobQueue, self.jobs),
            self.clock,
        )(DeleteMediaCommand(owner_id=self.asset.owner_id, media_id=self.asset.id))

    async def hide(self) -> None:
        await HideVariants(
            cast(UnitOfWork, Transactions()),
            cast(MediaRepository, self.assets),
            cast(MediaQuery, self.assets),
            cast(StoragePort, self.storage),
            cast(JobQueue, self.jobs),
            self.clock,
        )(HideVariantsCommand(media_id=self.asset.id))

    async def restore(self) -> None:
        await RestoreVariants(
            cast(UnitOfWork, Transactions()),
            cast(MediaRepository, self.assets),
            cast(MediaQuery, self.assets),
            cast(StoragePort, self.storage),
            cast(JobQueue, self.jobs),
        )(HideVariantsCommand(media_id=self.asset.id))

    async def run_hides(self) -> None:
        while self.jobs.take("media.hide_variants"):
            await self.hide()


async def test_moderator_rejects_again_while_variants_come_back() -> None:
    world = World()
    await world.decide(ModerationVerdict.APPROVED)
    assert world.jobs.take("media.restore_variants") == 1

    async def reject_again() -> None:
        await world.decide(ModerationVerdict.REJECTED)

    world.storage.before_copy = [reject_again]
    await world.restore()  # возврат докопировал варианты уже отклонённого фото
    assert world.asset.hidden_at is None  # страховка видит файл, пока скрытие не прошло

    await world.run_hides()

    assert world.public == set()
    assert world.private == world.keys
    assert world.asset.hidden_at is not None


async def test_owner_deletes_the_photo_while_variants_come_back() -> None:
    """Скрытие от удаления идёт одновременно с возвратом: отметка `hidden_at` ещё стоит, но
    скрытие всё равно переносит; что возврат скопировал после него, прячет его же передача."""
    world = World()
    await world.decide(ModerationVerdict.APPROVED)
    world.jobs.take("media.restore_variants")

    async def delete_and_hide() -> None:
        await world.delete()
        assert world.jobs.take("media.hide_variants") == 1
        await world.hide()  # другой воркер: пока возврат на первом ключе

    world.storage.before_copy = [delete_and_hide]
    await world.restore()
    assert world.public != set()  # возврат успел скопировать ключи после скрытия

    await world.run_hides()

    assert world.asset.status is MediaStatus.DELETED
    assert world.public == set()
    assert world.private == world.keys  # встречные переносы не потеряли ни одного варианта


async def test_retry_of_a_restore_hides_what_the_failed_attempt_copied() -> None:
    world = World()
    await world.decide(ModerationVerdict.APPROVED)
    world.jobs.take("media.restore_variants")

    async def fail() -> None:
        raise ConnectionError("storage")

    world.storage.before_copy = [_noop, fail]
    with pytest.raises(ConnectionError):
        await world.restore()  # первый ключ уже в media
    await world.decide(ModerationVerdict.REJECTED)
    world.jobs.take("media.hide_variants")  # скрытие от решения потерялось — не важно

    await world.restore()  # повтор задачи: файл снова отклонён
    assert (world.asset.hidden_at, world.jobs.names) == (None, ["media.hide_variants"])
    await world.run_hides()

    assert world.public == set()
    assert world.asset.hidden_at is not None


async def test_hiding_moves_what_is_public_even_when_marked_hidden() -> None:
    world = World()
    leftover = sorted(world.keys)[0]
    world.storage.buckets["media"].add(leftover)

    await world.hide()

    assert world.public == set()
    assert world.asset.hidden_at == T1


async def test_restore_copies_back_and_keeps_the_private_copy() -> None:
    world = World()
    await world.decide(ModerationVerdict.APPROVED)

    await world.restore()

    assert world.public == world.keys
    assert world.private == world.keys  # очистка удалённого файла стирает оба бакета
    assert world.asset.hidden_at is None
    assert world.jobs.names == ["media.restore_variants"]


async def _noop() -> None:
    return None
