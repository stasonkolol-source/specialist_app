"""Задачи identity (ADR-0020 §3).

- `identity.trust_aging` — раз в сутки: уровень доверия 1 тем, кто 14 дней без нарушений
  (ADR-0016 §2); понижает уровень сама санкция, сразу.
- `identity.revoke_restricted_sessions` — UserRestricted: приостановка и бан отзывают сессии.
- `identity.process_deletions` — ежечасно: удалить аккаунты, чей grace-период 7 дней прошёл
  (§7.10); с открытым кейсом модерации — ждать решения.
"""

from dishka import FromDishka

from app.modules.identity.application.ports import REVOKE_RESTRICTED_SESSIONS
from app.modules.identity.application.use_cases.age_trust_levels import (
    AgeTrustLevels,
    AgeTrustLevelsCommand,
)
from app.modules.identity.application.use_cases.process_deletions import (
    ProcessDeletions,
    ProcessDeletionsCommand,
)
from app.modules.identity.application.use_cases.revoke_restricted_sessions import (
    RevokeRestrictedSessions,
    RevokeRestrictedSessionsCommand,
)
from app.platform.contracts.events.identity import UserRestricted
from app.platform.queue.tasks import PeriodicRun, periodic, subscriber


@periodic("identity.trust_aging", cron="41 2 * * *")
async def trust_aging(run: PeriodicRun) -> None:
    async with run.container() as request:
        age = await request.get(AgeTrustLevels)
        await age(AgeTrustLevelsCommand())


@periodic("identity.process_deletions", cron="17 * * * *")
async def process_deletions(run: PeriodicRun) -> None:
    async with run.container() as request:
        process = await request.get(ProcessDeletions)
        await process(ProcessDeletionsCommand())


@subscriber(UserRestricted, REVOKE_RESTRICTED_SESSIONS)
async def revoke_restricted_sessions(
    event: UserRestricted, revoke: FromDishka[RevokeRestrictedSessions]
) -> None:
    await revoke(RevokeRestrictedSessionsCommand(user_id=event.user_id, kind=event.kind))
