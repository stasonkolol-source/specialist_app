"""Автопроверка объекта (subscriber `moderation.auto_check`, ARCHITECTURE §14.1, плана 2.6).

Объект ждёт проверки (ModerationRequested) → адаптер цели отдаёт текст → правила 2.4 →
omni-moderation → классификатор (уровень доверия 0 или флаг) → маршрут (domain/pipeline.py):
- публикация (у уровня 0 — с выборочной проверкой после неё);
- очередь: кейс P0/P1/P2, объект ждёт решения модератора;
- P0 по правилам: скрыть, заморозить аккаунт (приостановка до решения), кейс safety.
Внешние вызовы — до транзакции; публикация или скрытие, кейс и заморозка — в одной.
Решение записывается в audit_log. Модуль без адаптера цели (ещё не подключён) пропускается
с ошибкой в логе.
"""

from dataclasses import dataclass
from uuid import UUID

import structlog

from app.modules.identity.api import IdentityApi, RestrictionIn, RestrictionKind
from app.modules.moderation.application.content_rules import ContentRulesChecker
from app.modules.moderation.application.dto import ContentCheck
from app.modules.moderation.application.ports import (
    AutoCheckMetrics,
    ModerationTarget,
    ModerationTargets,
    TargetContent,
)
from app.modules.moderation.application.use_cases.open_case import CaseOpener, OpenCaseCommand
from app.modules.moderation.domain.cases import CaseTrigger, EntityType
from app.modules.moderation.domain.pipeline import (
    SAMPLE_RATE,
    Checks,
    Route,
    Routing,
    needs_classifier,
    route,
    sampled,
)
from app.platform.ai.port import Moderation, ModerationResult, PolicyClassifier
from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.config.port import FeatureFlags
from app.platform.db.port import UnitOfWork
from app.platform.db.retry import retry_on_conflict
from app.platform.kernel.ids import UserId

log = structlog.get_logger(__name__)

SAMPLE_RATE_FLAG = "moderation.sample_rate"
"""Параметр флага: доля публикаций уровня 0 на проверку после публикации (0–1)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class AutoCheckCommand:
    entity_type: EntityType
    entity_id: UUID
    author_id: UserId
    edit: bool = False


class AutoCheck:
    def __init__(
        self,
        uow: UnitOfWork,
        targets: ModerationTargets,
        rules: ContentRulesChecker,
        moderation: Moderation,
        classifier: PolicyClassifier,
        opener: CaseOpener,
        identity: IdentityApi,
        flags: FeatureFlags,
        metrics: AutoCheckMetrics,
        audit: AuditLog,
    ) -> None:
        self._uow, self._targets, self._rules = uow, targets, rules
        self._moderation, self._classifier, self._opener = moderation, classifier, opener
        self._identity, self._flags, self._metrics, self._audit = identity, flags, metrics, audit

    async def __call__(self, cmd: AutoCheckCommand) -> Routing | None:
        """Маршрут объекта; None — проверять нечего (нет адаптера или объект уже не ждёт)."""
        target = self._targets.get(cmd.entity_type)
        if target is None:
            log.error("moderation_target_missing", entity_type=cmd.entity_type.value)
            return None
        content = await target.content(cmd.entity_id)
        if content is None:
            return None
        routing = await self._route(cmd, content)
        await retry_on_conflict(lambda: self._apply(cmd, target, content, routing))
        self._metrics.observe(cmd.entity_type, routing.route)
        log.info(
            "moderation_auto_checked",
            entity_type=cmd.entity_type.value,
            route=routing.route.value,
            queue=routing.queue.value if routing.queue else None,
        )
        return routing

    async def _route(self, cmd: AutoCheckCommand, content: TargetContent) -> Routing:
        author = await self._identity.get_user(content.author_id)
        trust_level = author.trust_level if author is not None else 0
        rules = await self._rules.check(
            ContentCheck(
                author_id=content.author_id,
                kind=content.kind,
                content_id=cmd.entity_id,
                text=content.text,
            )
        )
        blank = not content.text.strip()
        omni = (
            ModerationResult(flagged=False)
            if blank
            else await self._moderation.check_text(content.text)
        )
        policy = None
        if not blank and needs_classifier(trust_level=trust_level, rules=rules, omni=omni):
            policy = await self._classifier.classify(content.text, kind=content.kind)
        return route(
            Checks(
                rules=rules,
                omni=omni,
                policy=policy,
                always_review=content.always_review,
                risky_category=content.risk_level >= 1,
                sampled=trust_level == 0 and sampled(cmd.entity_id, await self._sample_rate()),
            )
        )

    async def _apply(
        self,
        cmd: AutoCheckCommand,
        target: ModerationTarget,
        content: TargetContent,
        routing: Routing,
    ) -> None:
        async with self._uow:
            case_id = None
            if routing.route is Route.PUBLISH:
                await target.publish(cmd.entity_id, version=content.version, auto=True)
            elif routing.route is Route.BLOCK or (routing.flagged and content.visible):
                await target.hide(cmd.entity_id, reason_code=routing.reason_code or "other")
            if routing.queue is not None:
                case_id = await self._opener.open(
                    OpenCaseCommand(
                        queue=routing.queue,
                        entity_type=cmd.entity_type,
                        entity_id=cmd.entity_id,
                        subject_id=content.author_id,
                        trigger=_trigger(cmd, routing),
                        details={"signals": list(routing.signals)},
                        media_ids=content.media_ids,
                        entity_version=content.version,
                    )
                )
            if routing.route is Route.BLOCK and case_id is not None:
                # P0: заморозить до решения (§14.2); модератор, одобрив, снимет заморозку
                await self._identity.restrict(
                    RestrictionIn(
                        user_id=content.author_id,
                        kind=RestrictionKind.SUSPENDED,
                        reason_code=routing.reason_code or "other",
                        case_id=case_id,
                    )
                )
            await self._audit.record(
                AuditEntry(
                    action="moderation.auto_check",
                    actor_kind=ActorKind.SYSTEM,
                    entity_type=cmd.entity_type.value,
                    entity_id=cmd.entity_id,
                    changes={
                        "route": routing.route.value,
                        "queue": routing.queue.value if routing.queue else None,
                        "signals": list(routing.signals),
                        "case_id": str(case_id) if case_id else None,
                    },
                )
            )

    async def _sample_rate(self) -> float:
        value = await self._flags.value(SAMPLE_RATE_FLAG)
        if isinstance(value, int | float) and not isinstance(value, bool) and 0 <= value <= 1:
            return float(value)
        return SAMPLE_RATE


def _trigger(cmd: AutoCheckCommand, routing: Routing) -> CaseTrigger:
    if routing.post_review or routing.route is Route.BLOCK:
        return CaseTrigger.AUTO_FLAG
    return CaseTrigger.EDIT if cmd.edit else CaseTrigger.NEW_CONTENT
