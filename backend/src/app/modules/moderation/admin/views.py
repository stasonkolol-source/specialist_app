"""Разделы moderation в админке (DEVELOPMENT_PLAN 2.7b; ADR-0016, ADR-0020 §1).

- Кейсы, жалобы (4.7) и споры (6.1c) — только чтение строк. Решение — страница «Решить кейс»:
  обычный кейс решает DecideCase, спор — ResolveDispute с исходом сделки; страница спора
  показывает доказательства через InspectDispute, и каждый просмотр пишется в audit_log, как
  `cli dispute-show`.
- Контент-правила: из админки — слова, фразы, домены и регулярки (движок RE2 линеен при любом
  шаблоне — CHECK `regex_from_seed` снят миграцией moderation_0007). Правило проходит ту же
  проверку, что сид в `cli seeds-validate` (`compile_rule`: у регулярки — компиляция RE2, пустое
  совпадение, двойные буквы, вложенные квантификаторы); страница «Проверить правило» до записи
  показывает итог этой проверки, пробу на тексте и примеры набора rule_examples.yaml, у которых
  поменяется вердикт. Правка строки сида переводит её в `origin = admin`: следующий `cli seed` её
  не перезапишет и исходное правило заново не вставит — строку он узнаёт по `seed_key`, а не по
  шаблону (решение шага 2.7b — уточнять правила на реальных примерах без деплоя важнее, чем «сид
  — источник правды»); «Сохранить» без изменений строку сиду оставляет. Строки не удаляются —
  выключаются (`is_active`): по ним остаётся история кейсов, где правило сработало. Запись берёт
  advisory lock импорта словаря; каждое изменение — в audit_log; снимок правил этого процесса
  сбрасывается сразу, у остальных (worker) — за TTL снимка (60 с), без перезапуска.
"""

from dataclasses import replace
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
from app.modules.moderation.application.use_cases.try_content_rule import (
    TryContentRule,
    TryContentRuleCommand,
)
from app.modules.moderation.domain.cases import EntityType
from app.modules.moderation.domain.rules import (
    ContentRule,
    InvalidRuleError,
    RegexEngine,
    RuleAction,
    RuleCategory,
    RuleKind,
    compile_rule,
)
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
    can_delete = False
    help_text = (
        "Регулярка пишется по скелету текста (латиница в нижнем регистре, без двойных букв) в"
        " синтаксисе RE2 — без lookaround и обратных ссылок. Перед записью — страница «Проверить"
        " правило»: та же проверка, что у сида, проба на тексте и примеры набора, у которых"
        " поменяется вердикт. Правка действует в этом процессе сразу, в worker — за 60 секунд."
    )
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
    async def on_model_change(
        self, data: dict[str, Any], model: Any, is_created: bool, request: Request
    ) -> None:
        rule = form_rule(data, model)
        engine = await container_of(request).get(RegexEngine)
        try:
            compile_rule(rule, engine)  # та же проверка, что у сида в `cli seeds-validate`
        except InvalidRuleError as error:
            raise ValueError(f"Правило не принято: {error}") from None
        data["pattern"] = rule.pattern  # SQLAdmin пишет в строку поля формы после этого шага
        if is_created or _changes_row(data, model):
            model.origin = RuleOrigin.ADMIN  # строку сида дальше ведёт админка

    @override
    async def after_change(self, model: Any, request: Request) -> None:
        (await container_of(request).get(RuleSource)).invalidate()


def _changes_row(data: dict[str, Any], model: Any) -> bool:
    """Форма что-то меняет в строке: «Сохранить» без правок строку сида админке не передаёт — её
    по-прежнему ведёт `cli seed`."""
    return any(_value(value) != _value(getattr(model, key)) for key, value in data.items())


def _value(value: object) -> object:
    """Значение поля формы или колонки для сравнения: перечисление — строкой, пусто — None."""
    plain = getattr(value, "value", value)
    return None if plain == "" else plain


def form_rule(data: Any, model: Any = None) -> ContentRule:
    """Правило из полей формы; у правки — недостающее из строки."""

    def field(name: str) -> str:
        value = data.get(name) or (getattr(model, name, None) if model is not None else None)
        return str(getattr(value, "value", value) or "").strip()

    kind = RuleKind(field("kind"))
    pattern = field("pattern")
    if not pattern:
        raise ValueError("Пустое правило")
    # у регулярки регистр значим («\S» — не «\s»), слова и домены — в нижнем регистре
    return ContentRule(
        pattern=pattern if kind is RuleKind.REGEX else pattern.lower(),
        kind=kind,
        action=RuleAction(field("action")),
        category=RuleCategory(field("category")),
        id=getattr(model, "id", None) if model is not None else None,
    )


class ContentRuleTrialView(BaseView):
    """Проба правила до записи: проверка seeds-validate, текст и прогон по набору примеров."""

    name = "Проверить правило"
    icon = "fa-solid fa-vial"
    category = "Модерация"
    identity = "content-rule-trial"

    def is_accessible(self, request: Request) -> bool:
        return bool(staff_roles(request) & ADMIN)

    def is_visible(self, request: Request) -> bool:
        return self.is_accessible(request)

    @expose("/content-rule-trial", methods=["GET", "POST"])
    async def trial(self, request: Request) -> Response:
        source: Any = await request.form() if request.method == "POST" else request.query_params
        context: dict[str, object] = {
            "kinds": [kind.value for kind in RuleKind],
            "actions": [action.value for action in RuleAction],
            "categories": [category.value for category in RuleCategory],
            "form": {key: str(source.get(key, "")) for key in _TRIAL_FIELDS},
        }
        if request.method == "GET" and (raw := str(source.get("rule_id", "")).strip()):
            context["form"] = await self._stored(raw) or context["form"]
        if request.method == "POST":
            try:
                rule = form_rule(source)
            except ValueError as error:
                context["error"] = str(error) or "не хватает полей правила"
            else:
                rule_id = str(source.get("rule_id", "")).strip()
                context["trial"] = await run_action(
                    request,
                    TryContentRule,
                    TryContentRuleCommand(
                        rule=replace(rule, id=int(rule_id) if rule_id.isdigit() else None),
                        sample=str(source.get("sample", "")),
                    ),
                )
        return await self._admin_ref.templates.TemplateResponse(
            request, "admin/content_rule_trial.html", context
        )

    async def _stored(self, raw: str) -> dict[str, str] | None:
        """Форма пробы по строке словаря: «проверить» правку существующего правила."""
        if not raw.isdigit():
            return None
        async with self._admin_ref.session_maker() as session:
            row = await session.get(ContentRuleRow, int(raw))
        if row is None:
            return None
        return {
            "rule_id": str(row.id),
            "kind": row.kind.value,
            "pattern": row.pattern,
            "action": row.action.value,
            "category": row.category.value,
            "sample": "",
        }


_TRIAL_FIELDS = ("rule_id", "kind", "pattern", "action", "category", "sample")


VIEWS = (CaseAdmin, ReportAdmin, DecideCaseView, ContentRuleAdmin, ContentRuleTrialView)
