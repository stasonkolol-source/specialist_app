"""`cli moderation-queue` и `cli moderation-decide`: кейсы модерации до чата модераторов (2.5b)
и админки (2.7b) — решение владельца 2026-10-01: сначала ядро продукта.

Решает тот, у кого есть роль модератора или администратора (`cli staff-grant`): кто — по
Telegram id из `--by`, решение записывается от его имени, как из чата модераторов.
"""

from dataclasses import dataclass

from dishka import AsyncContainer

from app.platform.kernel.clock import BUSINESS_TZ

DECIDERS = frozenset({"moderator", "admin"})


@dataclass(frozen=True, slots=True)
class CliOutcome:
    ok: bool
    lines: tuple[str, ...]


async def moderation_queue(container: AsyncContainer, *, limit: int) -> CliOutcome:
    from app.modules.moderation.application.queries import ModerationQueries

    async with container() as request:
        views = await (await request.get(ModerationQueries)).open_cases(limit=limit)
    if not views:
        return CliOutcome(ok=True, lines=("moderation queue is empty",))
    return CliOutcome(
        ok=True,
        lines=tuple(
            f"{view.id}  {view.queue.value:<7} {view.entity_type}/{view.entity_id}"
            f"  {view.trigger:<11} {view.status.value:<9}"
            f" due {view.due_at.astimezone(BUSINESS_TZ):%d.%m %H:%M}"
            f"  {', '.join(view.signals) or '—'}"
            for view in views
        ),
    )


async def moderation_decide(
    container: AsyncContainer,
    *,
    case_ref: str,
    approve: bool,
    by_telegram_id: int,
    reason: str | None,
    severity: str | None,
    note: str | None,
) -> CliOutcome:
    from app.modules.identity.api import IdentityApi
    from app.modules.moderation.application.use_cases.decide_case import (
        DecideCase,
        DecideCaseCommand,
    )
    from app.modules.moderation.domain.sanctions import Severity
    from app.platform.contracts.events.moderation import ModerationDecision
    from app.platform.kernel.errors import DomainError
    from app.platform.kernel.ids import CaseId, parse_id

    try:
        case_id = CaseId(parse_id(case_ref))
    except ValueError:
        return CliOutcome(ok=False, lines=(f"moderation-decide: not a case id: {case_ref}",))
    async with container() as request:
        identity = await request.get(IdentityApi)
        moderator = await identity.by_telegram(by_telegram_id)
        if moderator is None:
            return CliOutcome(ok=False, lines=("moderation-decide: no such Telegram user",))
        if not {role.value for role in await identity.roles(moderator.id)} & DECIDERS:
            return CliOutcome(
                ok=False, lines=("moderation-decide: not a moderator (see staff-grant)",)
            )
        decide = await request.get(DecideCase)
        try:
            decision = await decide(
                DecideCaseCommand(
                    case_id=case_id,
                    verdict=ModerationDecision.APPROVED if approve else ModerationDecision.REJECTED,
                    reason_code=reason,
                    severity=Severity(severity) if severity else None,
                    moderator_id=moderator.id,
                    note=note,
                )
            )
        except DomainError as error:
            return CliOutcome(ok=False, lines=(f"moderation-decide: {error.code} {error.params}",))
    sanction = f", sanction {decision.sanction.value}" if decision.sanction else ""
    return CliOutcome(
        ok=True, lines=(f"case {decision.case_id}: {decision.status.value}{sanction}",)
    )
