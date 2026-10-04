"""Разделы moderation в админке (DEVELOPMENT_PLAN 2.7b; ADR-0016, ADR-0020 §1).

- Кейсы, жалобы (4.7) и споры (6.1c) — только чтение строк. Решение — страница «Решить кейс»:
  обычный кейс решает DecideCase, спор — ResolveDispute с исходом сделки; страница спора
  показывает доказательства через InspectDispute, и каждый просмотр пишется в audit_log, как
  `cli dispute-show`.
- Контент-правила: из админки — слова, фразы и домены; регулярки — только из сида (CHECK
  `regex_from_seed`, `re` не ограничивает время перебора), в админке они только для чтения.
  Правка строки сида переводит её в `origin = admin`: следующий `cli seed` её не перезапишет
  (решение шага 2.7b — правка на реальных примерах без деплоя важнее, чем «сид — источник
  правды»); чтобы вернуть строку сиду, её удаляют — `cli seed` создаст заново. Запись берёт
  advisory lock импорта словаря; каждое изменение — в audit_log; снимок правил этого процесса
  сбрасывается сразу, у остальных (worker) — за TTL снимка (60 с), без перезапуска.
"""

from typing import Any, ClassVar, override
from uuid import UUID

from sqladmin import BaseView, expose
from starlette.requests import Request
from starlette.responses import Response

from app.modules.moderation.application.ports import RuleSource
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
from app.modules.moderation.domain.cases import EntityType
from app.modules.moderation.domain.rules import RuleKind
from app.modules.moderation.domain.sanctions import Severity
from app.modules.moderation.infrastructure.models import (
    IMPORT_LOCK,
    CaseRow,
    ContentRuleRow,
    ReportRow,
    RuleOrigin,
)
from app.platform.contracts.events.moderation import ModerationDecision
from app.platform.http.admin import (
    ADMIN,
    MODERATION,
    StaffModelView,
    container_of,
    run_action,
    staff_id,
    staff_roles,
)
from app.platform.kernel.errors import DomainError
from app.platform.kernel.ids import CaseId


class CaseAdmin(StaffModelView, model=CaseRow):
    name = "Кейс"
    name_plural = "Кейсы"
    icon = "fa-solid fa-scale-balanced"
    category = "Модерация"
    roles = MODERATION
    audit_entity = "moderation.case"
    can_create = can_edit = can_delete = False
    column_list: ClassVar[Any] = [
        CaseRow.id,
        CaseRow.queue,
        CaseRow.entity_type,
        CaseRow.entity_id,
        CaseRow.trigger,
        CaseRow.status,
        CaseRow.due_at,
        CaseRow.created_at,
    ]
    column_searchable_list: ClassVar[Any] = [CaseRow.id, CaseRow.entity_id, CaseRow.subject_id]
    column_sortable_list: ClassVar[Any] = [CaseRow.due_at, CaseRow.created_at, CaseRow.status]
    column_default_sort: ClassVar[Any] = [(CaseRow.created_at, True)]


class ReportAdmin(StaffModelView, model=ReportRow):
    name = "Жалоба"
    name_plural = "Жалобы"
    icon = "fa-solid fa-flag"
    category = "Модерация"
    roles = MODERATION
    audit_entity = "moderation.report"
    can_create = can_edit = can_delete = False
    column_list: ClassVar[Any] = [
        ReportRow.id,
        ReportRow.target_type,
        ReportRow.target_id,
        ReportRow.reason,
        ReportRow.status,
        ReportRow.case_id,
        ReportRow.created_at,
    ]
    column_searchable_list: ClassVar[Any] = [ReportRow.case_id, ReportRow.target_id]
    column_default_sort: ClassVar[Any] = [(ReportRow.created_at, True)]


class DecideCaseView(BaseView):
    """Решение по кейсу или спору — через use case, от имени вошедшего модератора."""

    name = "Решить кейс"
    icon = "fa-solid fa-gavel"
    category = "Модерация"
    identity = "decide-case"

    def is_accessible(self, request: Request) -> bool:
        return bool(staff_roles(request) & MODERATION)

    def is_visible(self, request: Request) -> bool:
        return self.is_accessible(request)

    @expose("/decide-case", methods=["GET", "POST"])
    async def decide(self, request: Request) -> Response:
        source = await request.form() if request.method == "POST" else request.query_params
        raw = str(source.get("case_id", "")).strip()
        context: dict[str, object] = {
            "case_id": raw,
            "severities": [severity.value for severity in Severity],
        }
        try:
            case_id = CaseId(UUID(raw)) if raw else None
        except ValueError:
            context["error"] = "not a case id"
            case_id = None
        if case_id is not None:
            try:
                await self._handle(request, case_id, source, context)
            except DomainError as error:
                context["error"] = f"{error.code} {error.params}"
        return await self._admin_ref.templates.TemplateResponse(
            request, "admin/decide_case.html", context
        )

    async def _kind(self, case_id: CaseId) -> EntityType | None:
        """Обычный кейс или спор: строка кейса — короткой сессией SQLAdmin."""
        async with self._admin_ref.session_maker() as session:
            row = await session.get(CaseRow, case_id)
            return None if row is None else EntityType(row.entity_type)

    async def _handle(
        self, request: Request, case_id: CaseId, source: Any, context: dict[str, object]
    ) -> None:
        kind = await self._kind(case_id)
        if kind is None:
            context["error"] = "case_not_found"
            return
        context["kind"] = kind.value
        if kind is EntityType.DISPUTE:
            # просмотр доказательств спора — в audit_log (ADR-0020 §4), как `cli dispute-show`
            context["dossier"] = await run_action(
                request,
                InspectDispute,
                InspectDisputeCommand(case_id=case_id, moderator_id=staff_id(request)),
            )
        if request.method != "POST":
            return
        severity_raw = str(source.get("severity", "")).strip()
        severity = Severity(severity_raw) if severity_raw else None
        reason = str(source.get("reason_code", "")).strip() or None
        note = str(source.get("note", "")).strip() or None
        if kind is EntityType.DISPUTE:
            resolved = await run_action(
                request,
                ResolveDispute,
                ResolveDisputeCommand(
                    case_id=case_id,
                    outcome=str(source.get("outcome", "")),
                    reason_code=reason or "",
                    moderator_id=staff_id(request),
                    severity=severity,
                    note=note,
                ),
            )
            context["done"] = f"{resolved.case_status.value}, deal {resolved.outcome}"
            return
        decision = await run_action(
            request,
            DecideCase,
            DecideCaseCommand(
                case_id=case_id,
                verdict=ModerationDecision.APPROVED
                if source.get("verdict") == "approved"
                else ModerationDecision.REJECTED,
                reason_code=reason,
                severity=severity,
                moderator_id=staff_id(request),
                note=note,
            ),
        )
        sanction = f", sanction {decision.sanction.value}" if decision.sanction else ""
        context["done"] = f"{decision.status.value}{sanction}"


class ContentRuleAdmin(StaffModelView, model=ContentRuleRow):
    name = "Контент-правило"
    name_plural = "Контент-правила"
    icon = "fa-solid fa-filter"
    category = "Модерация"
    roles = ADMIN
    audit_entity = "moderation.content_rule"
    advisory_lock = IMPORT_LOCK
    can_delete = True
    column_list: ClassVar[Any] = [
        ContentRuleRow.id,
        ContentRuleRow.kind,
        ContentRuleRow.pattern,
        ContentRuleRow.lang,
        ContentRuleRow.action,
        ContentRuleRow.category,
        ContentRuleRow.is_active,
        ContentRuleRow.origin,
    ]
    column_searchable_list: ClassVar[Any] = [ContentRuleRow.pattern]
    column_sortable_list: ClassVar[Any] = [ContentRuleRow.id, ContentRuleRow.kind]
    form_columns: ClassVar[Any] = [
        ContentRuleRow.kind,
        ContentRuleRow.pattern,
        ContentRuleRow.lang,
        ContentRuleRow.action,
        ContentRuleRow.category,
        ContentRuleRow.is_active,
    ]

    @override
    async def check_can_edit(self, request: Request, model: Any) -> bool:
        return model.kind is not RuleKind.REGEX and await super().check_can_edit(request, model)

    @override
    async def check_can_delete(self, request: Request, model: Any) -> bool:
        return model.kind is not RuleKind.REGEX and await super().check_can_delete(request, model)

    @override
    async def on_model_change(
        self, data: dict[str, Any], model: Any, is_created: bool, request: Request
    ) -> None:
        kind = RuleKind(data.get("kind") or model.kind)
        if kind is RuleKind.REGEX:
            raise ValueError("Регулярные выражения — только из сида (CHECK regex_from_seed)")
        pattern = str(data.get("pattern") or model.pattern or "").strip()
        if not pattern:
            raise ValueError("Пустое правило")
        model.pattern = pattern.lower()
        model.origin = RuleOrigin.ADMIN  # строку сида дальше ведёт админка

    @override
    async def after_change(self, model: Any, request: Request) -> None:
        (await container_of(request).get(RuleSource)).invalidate()


VIEWS = (CaseAdmin, ReportAdmin, DecideCaseView, ContentRuleAdmin)
