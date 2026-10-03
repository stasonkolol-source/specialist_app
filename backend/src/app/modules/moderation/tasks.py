"""Задачи moderation (ADR-0020 §3).

- `moderation.auto_check` — ModerationRequested: автопроверка объекта (§14.1, план 2.6).
- `moderation.rate_limit_signals` — раз в 15 минут: сигналы риска по систематическим 429
  (ARCHITECTURE §13.3).
- `moderation.record_reregistration` — UserRegistered: повторная регистрация после удаления
  аккаунта — сигнал риска (§7.10).
- Споры по сделкам (6.1c): `moderation.open_dispute_case` (DealDisputed) — кейс `dispute`,
  `moderation.note_dispute_answer` (DisputeAnswered) и `moderation.note_dispute_unanswered`
  (DisputeUnanswered) — поводы «ответ» и «нет ответа», `moderation.close_dispute_case`
  (DisputeWithdrawn) — кейс закрыт без решения.
"""

from dishka import FromDishka

from app.modules.moderation.application.ports import (
    AUTO_CHECK,
    CLOSE_DISPUTE_CASE,
    NOTE_DISPUTE_ANSWER,
    NOTE_DISPUTE_UNANSWERED,
    OPEN_DISPUTE_CASE,
    RECORD_REREGISTRATION,
)
from app.modules.moderation.application.use_cases.auto_check import AutoCheck, AutoCheckCommand
from app.modules.moderation.application.use_cases.record_rate_limit_signals import (
    RecordRateLimitSignals,
    RecordRateLimitSignalsCommand,
)
from app.modules.moderation.application.use_cases.record_reregistration import (
    RecordReregistration,
    RecordReregistrationCommand,
)
from app.modules.moderation.application.use_cases.track_dispute import (
    DisputeStep,
    TrackDispute,
    TrackDisputeCommand,
)
from app.modules.moderation.domain.cases import EntityType
from app.platform.contracts.events.deals import (
    DealDisputed,
    DisputeAnswered,
    DisputeUnanswered,
    DisputeWithdrawn,
)
from app.platform.contracts.events.identity import UserRegistered
from app.platform.contracts.events.moderation import ModerationRequested
from app.platform.queue.tasks import PeriodicRun, periodic, subscriber


@subscriber(ModerationRequested, AUTO_CHECK)
async def auto_check(event: ModerationRequested, check: FromDishka[AutoCheck]) -> None:
    await check(
        AutoCheckCommand(
            entity_type=EntityType(event.entity_type),
            entity_id=event.entity_id,
            author_id=event.author_id,
            edit=event.edit,
        )
    )


@subscriber(UserRegistered, RECORD_REREGISTRATION)
async def record_reregistration(
    event: UserRegistered, record: FromDishka[RecordReregistration]
) -> None:
    await record(
        RecordReregistrationCommand(
            user_id=event.user_id,
            reregistered=event.reregistered,
            had_sanctions=event.had_sanctions,
        )
    )


@subscriber(DealDisputed, OPEN_DISPUTE_CASE)
async def open_dispute_case(event: DealDisputed, track: FromDishka[TrackDispute]) -> None:
    await track(TrackDisputeCommand(dispute_id=event.dispute_id, step=DisputeStep.OPENED))


@subscriber(DisputeAnswered, NOTE_DISPUTE_ANSWER)
async def note_dispute_answer(event: DisputeAnswered, track: FromDishka[TrackDispute]) -> None:
    await track(TrackDisputeCommand(dispute_id=event.dispute_id, step=DisputeStep.ANSWERED))


@subscriber(DisputeUnanswered, NOTE_DISPUTE_UNANSWERED)
async def note_dispute_unanswered(
    event: DisputeUnanswered, track: FromDishka[TrackDispute]
) -> None:
    await track(TrackDisputeCommand(dispute_id=event.dispute_id, step=DisputeStep.UNANSWERED))


@subscriber(DisputeWithdrawn, CLOSE_DISPUTE_CASE)
async def close_dispute_case(event: DisputeWithdrawn, track: FromDishka[TrackDispute]) -> None:
    await track(TrackDisputeCommand(dispute_id=event.dispute_id, step=DisputeStep.WITHDRAWN))


@periodic("moderation.rate_limit_signals", cron="4,19,34,49 * * * *")
async def rate_limit_signals(run: PeriodicRun) -> None:
    async with run.container() as request:
        record = await request.get(RecordRateLimitSignals)
        await record(RecordRateLimitSignalsCommand())
