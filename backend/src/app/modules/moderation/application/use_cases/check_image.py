"""Проверка фото (subscriber `moderation.check_image`; ARCHITECTURE §10.3 «Модерация», §14.1;
ADR-0016 §3–4; DEVELOPMENT_PLAN 6.7).

Фото обработано (MediaReady: фото профиля, работа портфолио, фото заявки; у ролика — постер) →
вариант `md` без EXIF уходит в omni-moderation `data:` URL → вердикт по порогам категорий
(domain/images.py):
- чисто — у файла `approved`;
- REVIEW — `flagged` и кейс P2 (premod): фото остаётся, решает модератор;
- BLOCK — `rejected`: API фото больше не показывает, варианты уходят в приватный бакет; кейс P0
  (safety, ≤ 1 ч). Аккаунт не замораживается — санкцию ставит модератор.
Проверка, которая не состоялась (нет ключа на stage и проде, сбой, открытый предохранитель), —
тоже P2: без проверки фото не считается чистым (ADR-0016). Задача упала после всех повторов
или не прочитала вариант — фото осталось бы `pending`: `moderation.recheck_images` раз в 10
минут ставит проверку снова, а через час без итога отдаёт фото модератору (P2). Второго
проверяющего нет (Q20: по умолчанию «пока без него»).

Кейс — об объекте `media` (адаптер цели targets/media.py): одобрение возвращает фото, отказ
скрывает его; файл — доказательство под legal hold, пока кейс открыт. Работа портфолио ждёт
итога фото (адаптер `portfolio`): чистое фото в той же транзакции снова отправляет ждущие работы
с ним на автопроверку подписи (`SpecialistsApi.recheck_works`); на флаге — ждут модератора,
при P0 фото скрыто, и в кабинете работа — «Не подходит». Вызов провайдера — до
транзакции; итог у файла, кейс и запись в audit_log — в одной. Повтор задачи после commit
провайдера не зовёт: файл уже проверен (`image_for_check` — None), решение модератора
автопроверка не перезаписывает. Стоимость — один вызов на фото, omni-moderation бесплатен. В
логах — только id, итог и категории с оценками.
"""

from dataclasses import dataclass
from typing import Final

import structlog

from app.modules.media.api import MediaApi, ModerationVerdict
from app.modules.moderation.application.ports import AutoCheckMetrics
from app.modules.moderation.application.use_cases.open_case import CaseOpener, OpenCaseCommand
from app.modules.moderation.domain.cases import CaseTrigger, EntityType
from app.modules.moderation.domain.images import (
    UNCHECKED,
    ImageAction,
    ImageVerdict,
    judge_image,
)
from app.modules.moderation.domain.pipeline import Route
from app.modules.specialists.api import SpecialistsApi
from app.platform.ai.port import Moderation
from app.platform.ai.prompt import image_data_url
from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.db.port import UnitOfWork
from app.platform.db.retry import retry_on_conflict
from app.platform.kernel.errors import ExternalServiceError
from app.platform.kernel.ids import CaseId, MediaId, UserId

log = structlog.get_logger(__name__)

PORTFOLIO_PURPOSE: Final = "portfolio"
IMAGE_PURPOSES: Final = frozenset({"avatar", PORTFOLIO_PURPOSE, "job"})
"""Чьи фото проверяются (`MediaReady.purpose`): все, что видят другие люди. Доказательства спора
смотрит модератор в кейсе P1 (6.1c), сообщения и отзывы с фото — v1."""

_STATUS: Final = {
    ImageAction.CLEAN: ModerationVerdict.APPROVED,
    ImageAction.REVIEW: ModerationVerdict.FLAGGED,
    ImageAction.BLOCK: ModerationVerdict.REJECTED,
}
_ROUTE: Final = {
    ImageAction.CLEAN: Route.PUBLISH,
    ImageAction.REVIEW: Route.REVIEW,
    ImageAction.BLOCK: Route.BLOCK,
}


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckImageCommand:
    media_id: MediaId
    owner_id: UserId
    purpose: str


class CheckImage:
    def __init__(
        self,
        uow: UnitOfWork,
        media: MediaApi,
        moderation: Moderation,
        opener: CaseOpener,
        metrics: AutoCheckMetrics,
        audit: AuditLog,
        specialists: SpecialistsApi,
    ) -> None:
        self._uow, self._media, self._moderation = uow, media, moderation
        self._opener, self._metrics, self._audit = opener, metrics, audit
        self._specialists = specialists

    async def __call__(self, cmd: CheckImageCommand) -> ImageVerdict | None:
        """Вердикт; None — проверять нечего (не готово, удалено, уже проверено)."""
        image = await self._media.image_for_check(cmd.media_id)
        if image is None:
            return None
        result = await self._moderation.check_image(image_data_url(image.body, image.content_type))
        return await self._record(cmd, judge_image(result))

    async def recheck(self, cmd: CheckImageCommand, *, may_give_up: bool) -> ImageVerdict | None:
        """Перепроверка (`moderation.recheck_image`). Сначала — обычная проверка: фото, загруженные
        до модерации фото, и сорвавшиеся проверки просто проверяются снова, а не уходят
        модератору. Модератору (P2, `give_up`) — только фото, ждущее итога дольше
        `GIVE_UP_AFTER` (`may_give_up`), которое проверить так и не вышло: вариант не читается
        (`image_for_check` — None) или хранилище недоступно."""
        try:
            verdict = await self(cmd)
        except ExternalServiceError:
            if not may_give_up:
                raise
            verdict = None
        if verdict is None and may_give_up:
            return await self.give_up(cmd)
        return verdict

    async def give_up(self, cmd: CheckImageCommand) -> ImageVerdict | None:
        """Проверка так и не состоялась (`moderation.recheck_images`): фото — модератору (P2),
        как при Unavailable. Без хранилища и провайдера: сбоят, скорее всего, они. None — итог
        уже записан или файл удалён."""
        return await self._record(cmd, UNCHECKED)

    async def _record(self, cmd: CheckImageCommand, verdict: ImageVerdict) -> ImageVerdict | None:
        recorded, case_id = await retry_on_conflict(lambda: self._apply(cmd, verdict))
        if not recorded:
            return None
        self._metrics.observe(EntityType.MEDIA, _ROUTE[verdict.action])
        log.info(
            "moderation_image_checked",
            media_id=str(cmd.media_id),
            action=verdict.action.value,
            signals=list(verdict.signals),
            case_id=str(case_id) if case_id else None,
        )
        return verdict

    async def _apply(
        self, cmd: CheckImageCommand, verdict: ImageVerdict
    ) -> tuple[bool, CaseId | None]:
        async with self._uow:
            recorded = await self._media.moderate(
                cmd.media_id, _STATUS[verdict.action], labels=verdict.labels, auto=True
            )
            if not recorded:  # удалили, пока проверяли, или итог уже записан
                return False, None
            if verdict.action is ImageAction.CLEAN and cmd.purpose == PORTFOLIO_PURPOSE:
                await self._specialists.recheck_works(cmd.media_id)
            case_id = None
            if verdict.queue is not None:
                case_id = await self._opener.open(
                    OpenCaseCommand(
                        queue=verdict.queue,
                        entity_type=EntityType.MEDIA,
                        entity_id=cmd.media_id,
                        subject_id=cmd.owner_id,
                        trigger=CaseTrigger.AUTO_FLAG,
                        details={
                            "event": f"image:{cmd.media_id}",
                            "signals": list(verdict.signals),
                            "purpose": cmd.purpose,
                            "hidden": verdict.action is ImageAction.BLOCK,
                            "reason": verdict.reason_code,
                        },
                        media_ids=(cmd.media_id,),
                    )
                )
            await self._audit.record(
                AuditEntry(
                    action="moderation.image_check",
                    actor_kind=ActorKind.SYSTEM,
                    entity_type=EntityType.MEDIA.value,
                    entity_id=cmd.media_id,
                    changes={
                        "action": verdict.action.value,
                        "queue": verdict.queue.value if verdict.queue else None,
                        "signals": list(verdict.signals),
                        "case_id": str(case_id) if case_id else None,
                    },
                )
            )
            return True, case_id
