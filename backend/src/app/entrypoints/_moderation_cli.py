"""`cli moderation-queue`, `cli moderation-decide`, `cli dispute-show`, `cli dispute-resolve` и
`cli moderation-demo`: кейсы модерации командами — рядом с кнопками чата модераторов (2.5b) и до
админки (2.7b). `moderation-demo` открывает демо-кейс об аккаунте: карточка в чате модераторов
(worker), решение кнопкой доходит до пользователя уведомлением.

Решает тот, у кого есть роль модератора или администратора (`cli staff-grant`): кто — по
Telegram id из `--by`, решение записывается от его имени, как из чата модераторов. Спор по
сделке (6.1c) — кейс `dispute`: `dispute-show` показывает его с фото-доказательствами (просмотр
пишется в audit_log), `dispute-resolve` решает с исходом сделки.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from dishka import AsyncContainer

from app.platform.kernel.clock import BUSINESS_TZ

if TYPE_CHECKING:
    from app.modules.media.api import MediaRef
    from app.platform.kernel.ids import MediaId, UserId

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
        moderator = await _moderator(request, "moderation-decide", by_telegram_id)
        if isinstance(moderator, CliOutcome):
            return moderator
        decide = await request.get(DecideCase)
        try:
            decision = await decide(
                DecideCaseCommand(
                    case_id=case_id,
                    verdict=ModerationDecision.APPROVED if approve else ModerationDecision.REJECTED,
                    reason_code=reason,
                    severity=Severity(severity) if severity else None,
                    moderator_id=moderator,
                    note=note,
                )
            )
        except DomainError as error:
            return CliOutcome(ok=False, lines=(f"moderation-decide: {error.code} {error.params}",))
    sanction = f", sanction {decision.sanction.value}" if decision.sanction else ""
    return CliOutcome(
        ok=True, lines=(f"case {decision.case_id}: {decision.status.value}{sanction}",)
    )


async def moderation_demo(container: AsyncContainer, *, telegram_id: int) -> CliOutcome:
    from app.modules.identity.api import IdentityApi
    from app.modules.moderation.application.ports import ModeratorsChat
    from app.modules.moderation.application.use_cases.open_case import (
        OpenCase,
        OpenCaseCommand,
    )
    from app.modules.moderation.domain.cases import CaseTrigger, EntityType
    from app.modules.moderation.domain.queues import Queue

    async with container() as request:
        user = await (await request.get(IdentityApi)).by_telegram(telegram_id)
        if user is None:
            return CliOutcome(ok=False, lines=("moderation-demo: no such Telegram user",))
        chat = await request.get(ModeratorsChat)
        case_id = await (await request.get(OpenCase))(
            OpenCaseCommand(
                queue=Queue.FRAUD,
                entity_type=EntityType.USER,
                entity_id=user.id,
                subject_id=user.id,
                trigger=CaseTrigger.AUTO_FLAG,
                details={"demo": True, "signals": ["demo"]},
            )
        )
    where = (
        "card goes to the moderators' chat (worker)"
        if chat.enabled
        else "TELEGRAM_MODERATORS_CHAT_ID is empty: no card, decide with moderation-decide"
    )
    return CliOutcome(ok=True, lines=(f"case {case_id}: user/{user.id}, fraud; {where}",))


async def _moderator(
    request: AsyncContainer, command: str, by_telegram_id: int
) -> UserId | CliOutcome:
    """Модератор по Telegram id или отказ: нет такого пользователя, нет роли."""
    from app.modules.identity.api import IdentityApi

    identity: IdentityApi = await request.get(IdentityApi)
    moderator = await identity.by_telegram(by_telegram_id)
    if moderator is None:
        return CliOutcome(ok=False, lines=(f"{command}: no such Telegram user",))
    if not {role.value for role in await identity.roles(moderator.id)} & DECIDERS:
        return CliOutcome(ok=False, lines=(f"{command}: not a moderator (see staff-grant)",))
    return moderator.id


async def dispute_show(
    container: AsyncContainer, *, case_ref: str, by_telegram_id: int
) -> CliOutcome:
    """Спор модератору: стороны, что случилось, ответ, сроки и ссылки на фото (5 минут)."""
    from app.modules.moderation.application.use_cases.inspect_dispute import (
        InspectDispute,
        InspectDisputeCommand,
    )
    from app.platform.kernel.errors import DomainError
    from app.platform.kernel.ids import CaseId, parse_id

    try:
        case_id = CaseId(parse_id(case_ref))
    except ValueError:
        return CliOutcome(ok=False, lines=(f"dispute-show: not a case id: {case_ref}",))
    async with container() as request:
        moderator = await _moderator(request, "dispute-show", by_telegram_id)
        if isinstance(moderator, CliOutcome):
            return moderator
        show = await request.get(InspectDispute)
        try:
            dossier = await show(InspectDisputeCommand(case_id=case_id, moderator_id=moderator))
        except DomainError as error:
            return CliOutcome(ok=False, lines=(f"dispute-show: {error.code} {error.params}",))
    dispute, deal = dossier.dispute, dossier.deal
    opener = "client" if deal is not None and dispute.opened_by == deal.client_id else "performer"
    lines = [
        f"case {dossier.case_id}  {dossier.queue.value}  {dossier.case_status.value}"
        f"  due {_local(dossier.due_at)}",
        f"dispute {dispute.id}  {dispute.status}  kind {dispute.kind}",
        f"deal {dispute.deal_id}  «{deal.title if deal is not None else '—'}»"
        f"  {deal.status if deal is not None else '—'}",
        f"opened {_local(dispute.created_at)} by {opener} {dispute.opened_by};"
        f" respondent {dispute.respondent_id}, answer by {_local(dispute.respond_by)}",
        f"description: {dispute.description}",
    ]
    if dispute.response is not None and dispute.responded_at is not None:
        lines.append(f"response {_local(dispute.responded_at)}: {dispute.response}")
    elif dispute.unanswered_at is not None:
        lines.append("response: none — 48 h passed (no_response)")
    else:
        lines.append("response: not yet")
    lines += _photos("photos (opener)", dispute.media_ids, dossier.photos)
    lines += _photos("photos (respondent)", dispute.response_media_ids, dossier.photos)
    if dispute.outcome is not None:
        lines.append(f"resolved: {dispute.outcome} ({dispute.reason_code})")
    return CliOutcome(ok=True, lines=tuple(lines))


async def dispute_resolve(
    container: AsyncContainer,
    *,
    case_ref: str,
    outcome: str,
    by_telegram_id: int,
    reason: str,
    severity: str | None,
    note: str | None,
) -> CliOutcome:
    """Решение по спору: исход сделки, причина и, если нужно, санкция второй стороне."""
    from app.modules.moderation.application.use_cases.resolve_dispute import (
        ResolveDispute,
        ResolveDisputeCommand,
    )
    from app.modules.moderation.domain.sanctions import Severity
    from app.platform.kernel.errors import DomainError
    from app.platform.kernel.ids import CaseId, parse_id

    try:
        case_id = CaseId(parse_id(case_ref))
    except ValueError:
        return CliOutcome(ok=False, lines=(f"dispute-resolve: not a case id: {case_ref}",))
    async with container() as request:
        moderator = await _moderator(request, "dispute-resolve", by_telegram_id)
        if isinstance(moderator, CliOutcome):
            return moderator
        resolve = await request.get(ResolveDispute)
        try:
            resolution = await resolve(
                ResolveDisputeCommand(
                    case_id=case_id,
                    outcome=outcome,
                    reason_code=reason,
                    moderator_id=moderator,
                    severity=Severity(severity) if severity else None,
                    note=note,
                )
            )
        except DomainError as error:
            return CliOutcome(ok=False, lines=(f"dispute-resolve: {error.code} {error.params}",))
    sanction = f", sanction {resolution.sanction.value}" if resolution.sanction else ""
    return CliOutcome(
        ok=True,
        lines=(
            f"case {resolution.case_id}: {resolution.case_status.value}{sanction};"
            f" deal {resolution.deal_id}: {resolution.outcome}",
        ),
    )


def _local(moment: datetime) -> str:
    return f"{moment.astimezone(BUSINESS_TZ):%d.%m %H:%M}"


def _photos(
    title: str, media_ids: Sequence[MediaId], refs: Mapping[MediaId, MediaRef]
) -> list[str]:
    """Самый крупный вариант каждого фото; файл ещё обрабатывается или пропал — так и пишем."""
    if not media_ids:
        return []
    lines = [f"{title}:"]
    for media_id in media_ids:
        ref = refs.get(media_id)
        if ref is None:
            lines.append(f"  {media_id}  deleted")
        elif not ref.variants:
            lines.append(f"  {media_id}  {ref.status}")
        else:
            lines.append(f"  {media_id}  {ref.variants[-1].url}")
    return lines
