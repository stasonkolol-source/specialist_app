"""Дубликаты фото портфолио (subscriber `moderation.check_duplicates`; ADR-0016 L6,
ARCHITECTURE §10.3 «Антифрод», §14.3; DEVELOPMENT_PLAN 7.6).

Фото портфолио обработано (MediaReady) → media ищет у других аккаунтов готовые фото портфолио
с почти тем же pHash → среди них есть работы портфолио — кейс P2 (premod) о профиле
загрузившего: признак фейкового портфолио, решает человек. Автоматически ничего не скрывается:
совпадение бывает и честным (мастер и его бригада, одна работа у двух исполнителей), а
модератор, отклонив кейс, вернёт профиль на правки (адаптер цели `profile`).

Загрузивший — тот, чьё фото обработано позже: раньше загруженное сравнивать было не с чем.
В кейсе обе стороны: файл и работа загрузившего (работы может ещё не быть — фото обработали
до прикрепления) и похожие работы с расстоянием; файлы — доказательства под legal hold, пока
кейс открыт. Свои фото не в счёт — их отсекает media. Повтор задачи не дописывает ту же копию
второй раз (`details.event`). В логах — только id и числа.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final
from uuid import UUID

import structlog

from app.modules.media.api import MediaApi, MediaDuplicate
from app.modules.moderation.application.ports import CaseRepository
from app.modules.moderation.application.use_cases.open_case import CaseOpener, OpenCaseCommand
from app.modules.moderation.domain.cases import CaseTrigger, EntityType
from app.modules.moderation.domain.queues import Queue
from app.modules.specialists.api import PortfolioWorkRef, SpecialistsApi
from app.platform.db.port import UnitOfWork
from app.platform.db.retry import retry_on_conflict
from app.platform.kernel.ids import CaseId, MediaId, UserId

log = structlog.get_logger(__name__)

PORTFOLIO: Final = "portfolio"
"""Назначение файла (`MediaReady.purpose`), фото которого сравниваются."""
SIGNAL: Final = "portfolio_duplicate"
"""Сигнал в карточке кейса: фото похоже на работу другого аккаунта."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckDuplicatesCommand:
    media_id: MediaId
    owner_id: UserId


class CheckDuplicates:
    def __init__(
        self,
        uow: UnitOfWork,
        cases: CaseRepository,
        opener: CaseOpener,
        media: MediaApi,
        specialists: SpecialistsApi,
    ) -> None:
        self._uow, self._cases, self._opener = uow, cases, opener
        self._media, self._specialists = media, specialists

    async def __call__(self, cmd: CheckDuplicatesCommand) -> CaseId | None:
        """Кейс, куда записан повод; None — копий нет или похожие фото не в портфолио."""
        found = await self._media.duplicates(cmd.media_id)
        if not found:
            return None
        profile = await self._specialists.profile_of(cmd.owner_id)
        if profile is None:  # без профиля нет портфолио: файл некуда прикрепить
            return None
        works = await self._specialists.works_by_media(
            [cmd.media_id, *(duplicate.media_id for duplicate in found)]
        )
        # похожий файл, которого нет в портфолио (не прикрепили или работу убрали), — не довод
        matches = [duplicate for duplicate in found if duplicate.media_id in works]
        if not matches:
            return None
        details = _details(cmd.media_id, works, matches)
        case_id = await retry_on_conflict(
            lambda: self._open(cmd, profile.id, details, [m.media_id for m in matches])
        )
        log.info(
            "portfolio_duplicates_found",
            media_id=str(cmd.media_id),
            matches=len(matches),
            distance=matches[0].distance,
            case_id=str(case_id),
        )
        return case_id

    async def _open(
        self,
        cmd: CheckDuplicatesCommand,
        profile_id: UUID,
        details: Mapping[str, object],
        matched: Sequence[MediaId],
    ) -> CaseId:
        async with self._uow:
            case = await self._cases.open_for_entity(EntityType.PROFILE, profile_id)
            if case is not None and case.has_event(str(details["event"])):
                return case.id  # повтор задачи: эта копия уже в кейсе
            return await self._opener.open(
                OpenCaseCommand(
                    queue=Queue.PREMOD,
                    entity_type=EntityType.PROFILE,
                    entity_id=profile_id,
                    subject_id=cmd.owner_id,
                    trigger=CaseTrigger.AUTO_FLAG,
                    details=details,
                    media_ids=(cmd.media_id, *matched),
                )
            )


def _details(
    media_id: MediaId,
    works: Mapping[MediaId, PortfolioWorkRef],
    matches: Sequence[MediaDuplicate],
) -> dict[str, object]:
    """Повод в кейсе: что загрузили и на какие работы похоже — id и расстояния, без текста."""
    own = works.get(media_id)
    return {
        "event": f"{SIGNAL}:{media_id}",
        "signals": [SIGNAL],
        "media_id": str(media_id),
        "work_id": str(own.id) if own is not None else None,
        "matches": [
            {
                "media_id": str(match.media_id),
                "work_id": str(works[match.media_id].id),
                "profile_id": str(works[match.media_id].profile_id),
                "distance": match.distance,
            }
            for match in matches
        ],
    }
