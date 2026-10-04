"""Admin API moderation (DEVELOPMENT_PLAN 2.7b; ARCHITECTURE §8.5, §14; ADR-0020 §1): кейсы, жалобы,
контент-правила.

Только moderator и admin. Действия — те же use cases, что у SQLAdmin, чата модераторов и `cli`,
от имени вошедшего сотрудника: взять (TakeCase), эскалировать (EscalateCase), решить (DecideCase),
решить спор с исходом сделки (ResolveDispute). Доказательства спора — InspectDispute: каждый
просмотр пишется в audit_log (`moderation.dispute.evidence_viewed`), как `cli dispute-show`.
Контент-правила (часть 2) — только admin, тем же путём, что раздел SQLAdmin (`apply_change` с
хуками `ContentRuleAdmin`): проверка `compile_rule` с движком RE2 (та же, что у сида в
`cli seeds-validate`), регистр регулярки сохраняется, слова и домены — в нижнем регистре, правка
строки сида переводит её в `origin = admin`, строки не удаляются, а выключаются; аудит
`moderation.content_rule.created|updated` и сброс снимка правил (этот процесс — сразу, worker — за
60 с). Проба до записи — TryContentRule, как страница «Проверить правило».
Сборка, вход, CSRF и лимит — interfaces/http/admin_api.py.
"""

from dataclasses import replace
from typing import Annotated, Literal
from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.moderation.admin.schemas import (
    CaseOut,
    ContentRuleIn,
    ContentRuleOut,
    ContentRulePatchIn,
    ContentRuleTrialIn,
    ContentRuleTrialOut,
    DecideIn,
    DecisionOut,
    DisputeDossierOut,
    DisputeResolutionOut,
    EscalateIn,
    ReportOut,
    ResolveDisputeIn,
)
from app.modules.moderation.admin.views import ContentRuleAdmin, form_rule
from app.modules.moderation.application.dto import CaseFilter, ReportFilter
from app.modules.moderation.application.queries import StaffQueries
from app.modules.moderation.application.use_cases.decide_case import (
    DecideCase,
    DecideCaseCommand,
)
from app.modules.moderation.application.use_cases.inspect_dispute import (
    InspectDispute,
    InspectDisputeCommand,
)
from app.modules.moderation.application.use_cases.resolve_dispute import (
    ResolveDispute,
    ResolveDisputeCommand,
)
from app.modules.moderation.application.use_cases.take_case import (
    EscalateCase,
    EscalateCaseCommand,
    TakeCase,
    TakeCaseCommand,
)
from app.modules.moderation.application.use_cases.try_content_rule import (
    TryContentRule,
    TryContentRuleCommand,
)
from app.modules.moderation.domain.cases import CaseStatus, EntityType
from app.modules.moderation.domain.queues import Queue
from app.modules.moderation.domain.reports import ReportStatus
from app.modules.moderation.domain.rules import RuleKind
from app.platform.contracts.events.moderation import ModerationDecision
from app.platform.http.admin import (
    ADMIN,
    MODERATION,
    AdminRows,
    InvalidAdminChangeError,
    apply_change,
    as_row,
    staff_id,
    table_of,
)
from app.platform.http.pagination import PageOut, PageParams
from app.platform.http.staff import staff_only
from app.platform.kernel.errors import NotFoundError
from app.platform.kernel.ids import CaseId, UserId

router = APIRouter(tags=["moderation"])


@router.get("/cases", response_model=PageOut[CaseOut], **staff_only(MODERATION))
@inject
async def list_cases(
    page: PageParams,
    queries: FromDishka[StaffQueries],
    queue: Annotated[
        list[Queue] | None,
        Query(description="Очередь — приоритет: safety — P0, fraud — P1, premod — P2"),
    ] = None,
    status: Annotated[list[CaseStatus] | None, Query()] = None,
    entity_type: EntityType | None = None,
    subject_id: Annotated[
        UUID | None, Query(description="Кейсы о пользователе: история его модерации")
    ] = None,
    assigned_to: UUID | None = None,
    order: Annotated[
        Literal["due", "recent"],
        Query(description="due — ближний срок первым (очередь), recent — новые первыми"),
    ] = "due",
) -> PageOut[CaseOut]:
    """Очередь модерации с фильтрами."""
    found = await queries.cases(
        CaseFilter(
            queues=tuple(queue or ()),
            statuses=tuple(status or ()),
            entity_type=entity_type,
            subject_id=UserId(subject_id) if subject_id is not None else None,
            assigned_to=UserId(assigned_to) if assigned_to is not None else None,
            recent_first=order == "recent",
        ),
        page,
    )
    return PageOut.of(found, CaseOut.of)


@router.get("/cases/{case_id}", response_model=CaseOut, **staff_only(MODERATION))
@inject
async def get_case(case_id: UUID, queries: FromDishka[StaffQueries]) -> CaseOut:
    """Кейс с поводами; фото спора — `GET /cases/{case_id}/dispute` (с записью в аудит)."""
    return CaseOut.of(await queries.case(CaseId(case_id)))


@router.post("/cases/{case_id}/take", response_model=CaseOut, **staff_only(MODERATION))
@inject
async def take_case(
    case_id: UUID, request: Request, take: FromDishka[TakeCase], queries: FromDishka[StaffQueries]
) -> CaseOut:
    """Взять кейс в работу; повтор тем же сотрудником ничего не меняет, чужой — 409 case_taken."""
    await take(TakeCaseCommand(case_id=CaseId(case_id), moderator_id=staff_id(request)))
    return CaseOut.of(await queries.case(CaseId(case_id)))


@router.post("/cases/{case_id}/escalate", response_model=CaseOut, **staff_only(MODERATION))
@inject
async def escalate_case(
    case_id: UUID,
    body: EscalateIn,
    request: Request,
    escalate: FromDishka[EscalateCase],
    queries: FromDishka[StaffQueries],
) -> CaseOut:
    """Отдать старшему: кейс снова свободен, его берёт администратор."""
    await escalate(
        EscalateCaseCommand(case_id=CaseId(case_id), moderator_id=staff_id(request), note=body.note)
    )
    return CaseOut.of(await queries.case(CaseId(case_id)))


@router.post("/cases/{case_id}/decide", response_model=DecisionOut, **staff_only(MODERATION))
@inject
async def decide_case(
    case_id: UUID, body: DecideIn, request: Request, decide: FromDishka[DecideCase]
) -> DecisionOut:
    """Решение по кейсу: statement of reasons автору, санкция по лестнице (DecideCase). Спор так
    не решить — 409 case_kind_conflict, для него `resolve-dispute`."""
    decision = await decide(
        DecideCaseCommand(
            case_id=CaseId(case_id),
            verdict=ModerationDecision(body.verdict),
            reason_code=body.reason_code,
            severity=body.severity,
            moderator_id=staff_id(request),
            note=body.note,
        )
    )
    return DecisionOut.of(decision)


@router.get("/cases/{case_id}/dispute", response_model=DisputeDossierOut, **staff_only(MODERATION))
@inject
async def inspect_dispute(
    case_id: UUID, request: Request, inspect: FromDishka[InspectDispute]
) -> DisputeDossierOut:
    """Спор и фото обеих сторон (ссылки на 5 минут); каждый просмотр — в журнале аудита."""
    dossier = await inspect(
        InspectDisputeCommand(case_id=CaseId(case_id), moderator_id=staff_id(request))
    )
    return DisputeDossierOut.of(dossier)


@router.post(
    "/cases/{case_id}/resolve-dispute",
    response_model=DisputeResolutionOut,
    **staff_only(MODERATION),
)
@inject
async def resolve_dispute(
    case_id: UUID, body: ResolveDisputeIn, request: Request, resolve: FromDishka[ResolveDispute]
) -> DisputeResolutionOut:
    """Решение по спору: исход сделки, решение по кейсу и санкция — одной транзакцией."""
    resolved = await resolve(
        ResolveDisputeCommand(
            case_id=CaseId(case_id),
            outcome=body.outcome,
            reason_code=body.reason_code,
            moderator_id=staff_id(request),
            severity=body.severity,
            note=body.note,
        )
    )
    return DisputeResolutionOut.of(resolved)


@router.get("/reports", response_model=PageOut[ReportOut], **staff_only(MODERATION))
@inject
async def list_reports(
    page: PageParams,
    queries: FromDishka[StaffQueries],
    status: Annotated[list[ReportStatus] | None, Query()] = None,
    target_type: EntityType | None = None,
    target_id: UUID | None = None,
    case_id: UUID | None = None,
    reporter_id: UUID | None = None,
) -> PageOut[ReportOut]:
    """Жалобы, новые первыми."""
    found = await queries.reports(
        ReportFilter(
            statuses=tuple(status or ()),
            target_type=target_type,
            target_id=target_id,
            case_id=CaseId(case_id) if case_id is not None else None,
            reporter_id=UserId(reporter_id) if reporter_id is not None else None,
        ),
        page,
    )
    return PageOut.of(found, ReportOut.of)


@router.get("/reports/{report_id}", response_model=ReportOut, **staff_only(MODERATION))
@inject
async def get_report(report_id: UUID, queries: FromDishka[StaffQueries]) -> ReportOut:
    return ReportOut.of(await queries.report(report_id))


@router.get("/content-rules", response_model=PageOut[ContentRuleOut], **staff_only(ADMIN))
@inject
async def list_content_rules(
    page: PageParams,
    session: FromDishka[AsyncSession],
    kind: RuleKind | None = None,
    is_active: Annotated[bool | None, Query()] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
) -> PageOut[ContentRuleOut]:
    """Словарь правил: слова, регулярки по скелету, домены; `origin` — кто ведёт строку."""
    table = table_of(ContentRuleAdmin)
    where = []
    if kind is not None:
        where.append(table.c.kind == kind.value)
    if is_active is not None:
        where.append(table.c.is_active.is_(is_active))
    if q:
        where.append(table.c.pattern.icontains(q, autoescape=True))
    return PageOut.of(await AdminRows(session).page(table, page, *where), ContentRuleOut.of)


@router.post(
    "/content-rules",
    status_code=status.HTTP_201_CREATED,
    response_model=ContentRuleOut,
    **staff_only(ADMIN),
)
async def create_content_rule(body: ContentRuleIn, request: Request) -> ContentRuleOut:
    """Новое правило: та же проверка, что у сида; 422 invalid_admin_change — с причиной."""
    model = await apply_change(request, ContentRuleAdmin(), None, body.model_dump())
    return ContentRuleOut.of(as_row(model))


@router.patch("/content-rules/{rule_id}", response_model=ContentRuleOut, **staff_only(ADMIN))
async def update_content_rule(
    rule_id: int, body: ContentRulePatchIn, request: Request
) -> ContentRuleOut:
    """Правка или выключение (`is_active: false`) правила; строка сида переходит к админке."""
    model = await apply_change(
        request, ContentRuleAdmin(), rule_id, body.model_dump(exclude_unset=True)
    )
    if model is None:
        raise NotFoundError(rule_id=rule_id)
    return ContentRuleOut.of(as_row(model))


@router.post("/content-rules/trial", response_model=ContentRuleTrialOut, **staff_only(ADMIN))
@inject
async def try_content_rule(
    body: ContentRuleTrialIn, trial: FromDishka[TryContentRule]
) -> ContentRuleTrialOut:
    """Проба до записи (ничего не пишет): итог проверки, срабатывание на тексте и примеры набора
    rule_examples.yaml, у которых поменяется вердикт; `rule_id` — правка этой строки."""
    try:
        rule = form_rule(body.model_dump(exclude={"rule_id", "sample"}))
    except ValueError as error:
        raise InvalidAdminChangeError(reason=str(error)) from None
    result = await trial(
        TryContentRuleCommand(rule=replace(rule, id=body.rule_id), sample=body.sample)
    )
    return ContentRuleTrialOut.of(result)
