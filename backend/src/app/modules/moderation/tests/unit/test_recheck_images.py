"""Фото без итога проверки (DEVELOPMENT_PLAN 6.7): задача проверки упала или не прочитала
вариант — периодическая страховка ставит проверку снова, а через час отдаёт фото модератору."""

from collections.abc import Collection, Mapping
from datetime import datetime, timedelta
from typing import Any, Self, cast

import pytest

from app.modules.media.api import (
    ImageForCheck,
    MediaApi,
    ModerationVerdict,
    UncheckedImage,
)
from app.modules.moderation.application.dto import RecheckImagePayload
from app.modules.moderation.application.ports import AutoCheckMetrics
from app.modules.moderation.application.use_cases.check_image import (
    IMAGE_PURPOSES,
    CheckImage,
    CheckImageCommand,
)
from app.modules.moderation.application.use_cases.open_case import CaseOpener, OpenCaseCommand
from app.modules.moderation.application.use_cases.recheck_images import (
    RecheckImages,
    RecheckImagesCommand,
)
from app.modules.moderation.domain.cases import EntityType
from app.modules.moderation.domain.images import UNCHECKED
from app.modules.moderation.domain.pipeline import Route
from app.modules.moderation.domain.queues import Queue
from app.modules.moderation.tests.fakes import FakeMetrics
from app.modules.specialists.api import SpecialistsApi
from app.platform.ai.port import Moderation
from app.platform.audit.port import AuditEntry, AuditLog
from app.platform.db.port import UnitOfWork
from app.platform.kernel.errors import ExternalServiceError
from app.platform.kernel.ids import CaseId, MediaId, UserId, new_id
from app.platform.queue.port import JobQueue
from app.platform.testing.clock import FakeClock

pytestmark = pytest.mark.unit

OWNER = UserId(new_id())


class Transactions:
    def __init__(self) -> None:
        self.opened = 0

    async def __aenter__(self) -> Self:
        self.opened += 1
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class Media:
    """MediaApi: фото без итога и запись итога; хранилища нет — его трогать нельзя."""

    def __init__(self, *images: UncheckedImage) -> None:
        self.images = list(images)
        self.asked: dict[str, Any] = {}
        self.verdicts: list[tuple[MediaId, ModerationVerdict, bool]] = []

    async def unchecked_images(
        self, *, processed_before: datetime, purposes: Collection[str], limit: int
    ) -> list[UncheckedImage]:
        self.asked = {"before": processed_before, "purposes": set(purposes), "limit": limit}
        return self.images

    async def image_for_check(self, media_id: MediaId) -> ImageForCheck | None:
        raise AssertionError("отказ от проверки не читает хранилище")

    async def moderate(
        self,
        media_id: MediaId,
        verdict: ModerationVerdict,
        *,
        labels: Mapping[str, float] | None = None,
        auto: bool = False,
    ) -> bool:
        if self.verdicts:  # итог уже записан: опоздавшая проверка ничего не меняет
            return False
        self.verdicts.append((media_id, verdict, auto))
        return True


class Jobs:
    def __init__(self) -> None:
        self.queued: list[tuple[str, Any, str | None]] = []

    async def enqueue(self, task: Any, payload: Any, *, dedup_key: str | None = None) -> None:
        self.queued.append((task.name, payload, dedup_key))


class Opener:
    def __init__(self) -> None:
        self.opened: list[OpenCaseCommand] = []

    async def open(self, cmd: OpenCaseCommand) -> CaseId:
        self.opened.append(cmd)
        return CaseId(new_id())


class Audit:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


def image(age: timedelta, clock: FakeClock) -> UncheckedImage:
    return UncheckedImage(
        media_id=MediaId(new_id()),
        owner_id=OWNER,
        purpose="portfolio",
        processed_at=clock.now() - age,
    )


async def test_stale_photos_are_checked_again_and_the_oldest_go_to_a_moderator() -> None:
    clock = FakeClock()
    fresh, old = image(timedelta(minutes=20), clock), image(timedelta(hours=2), clock)
    media, jobs, uow = Media(fresh, old), Jobs(), Transactions()

    count = await RecheckImages(
        cast(UnitOfWork, uow), cast(MediaApi, media), cast(JobQueue, jobs), clock
    )(RecheckImagesCommand())

    assert count == 2
    assert media.asked == {
        "before": clock.now() - timedelta(minutes=15),  # свежие проверяет задача по MediaReady
        "purposes": set(IMAGE_PURPOSES),  # доказательства спора и прочее не проверяются
        "limit": 50,
    }
    assert jobs.queued == [
        (
            "moderation.recheck_image",
            RecheckImagePayload(media_id=fresh.media_id, owner_id=OWNER, purpose="portfolio"),
            str(fresh.media_id),
        ),
        (
            "moderation.recheck_image",
            RecheckImagePayload(
                media_id=old.media_id, owner_id=OWNER, purpose="portfolio", give_up=True
            ),
            str(old.media_id),
        ),
    ]
    assert uow.opened == 1


async def test_nothing_unchecked_needs_no_transaction() -> None:
    uow = Transactions()

    count = await RecheckImages(
        cast(UnitOfWork, uow), cast(MediaApi, Media()), cast(JobQueue, Jobs()), FakeClock()
    )(RecheckImagesCommand())

    assert (count, uow.opened) == (0, 0)


def check_image(media: Media) -> tuple[CheckImage, Opener, FakeMetrics]:
    opener, metrics = Opener(), FakeMetrics()
    check = CheckImage(
        cast(UnitOfWork, Transactions()),
        cast(MediaApi, media),
        cast(Moderation, object()),  # провайдер не зовётся
        cast(CaseOpener, opener),
        cast(AutoCheckMetrics, metrics),
        cast(AuditLog, Audit()),
        cast(SpecialistsApi, object()),  # на флаге работы ждут модератора
    )
    return check, opener, metrics


async def test_photo_that_was_never_checked_goes_to_a_moderator_like_unavailable() -> None:
    media = Media()
    check, opener, metrics = check_image(media)
    media_id = MediaId(new_id())
    cmd = CheckImageCommand(media_id=media_id, owner_id=OWNER, purpose="portfolio")

    verdict = await check.give_up(cmd)

    assert verdict is UNCHECKED
    assert media.verdicts == [(media_id, ModerationVerdict.FLAGGED, True)]  # фото остаётся видно
    [case] = opener.opened
    assert (case.queue, case.entity_type, case.entity_id) == (
        Queue.PREMOD,
        EntityType.MEDIA,
        media_id,
    )
    assert case.details["signals"] == ["image:unchecked"]
    assert metrics.routes == [(EntityType.MEDIA, Route.REVIEW)]

    # итог уже есть (проверка всё же прошла или модератор решил) — второй кейс не открывается
    assert await check.give_up(cmd) is None
    assert len(opener.opened) == 1


class Unreadable(Media):
    """Вариант фото не читается (хранилище отказало) — проверять нечего."""

    async def image_for_check(self, media_id: MediaId) -> ImageForCheck | None:
        return None


class StorageDown(Media):
    async def image_for_check(self, media_id: MediaId) -> ImageForCheck | None:
        raise ExternalServiceError(service="storage", reason="ConnectTimeoutError")


async def test_old_photo_that_still_cannot_be_read_goes_to_a_moderator() -> None:
    media = Unreadable()
    check, opener, _ = check_image(media)
    cmd = CheckImageCommand(media_id=MediaId(new_id()), owner_id=OWNER, purpose="avatar")

    assert await check.recheck(cmd, may_give_up=True) is UNCHECKED
    assert [case.details["signals"] for case in opener.opened] == [["image:unchecked"]]


async def test_fresh_photo_that_cannot_be_read_waits_for_the_next_round() -> None:
    media = Unreadable()
    check, opener, _ = check_image(media)
    cmd = CheckImageCommand(media_id=MediaId(new_id()), owner_id=OWNER, purpose="avatar")

    assert await check.recheck(cmd, may_give_up=False) is None
    assert (opener.opened, media.verdicts) == ([], [])


async def test_storage_outage_is_retried_and_only_an_old_photo_is_given_up() -> None:
    media = StorageDown()
    check, opener, _ = check_image(media)
    cmd = CheckImageCommand(media_id=MediaId(new_id()), owner_id=OWNER, purpose="job")

    with pytest.raises(ExternalServiceError):
        await check.recheck(cmd, may_give_up=False)  # задача повторится
    assert opener.opened == []

    assert await check.recheck(cmd, may_give_up=True) is UNCHECKED
    assert len(opener.opened) == 1
