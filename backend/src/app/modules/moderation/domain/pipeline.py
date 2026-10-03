"""Маршрут контента после автопроверок (ARCHITECTURE §14.1, ADR-0016 §3).

Правила → omni-moderation → классификатор (для уровня доверия 0 и при любом флаге).
- block в правилах — P0: скрыть, заморозить аккаунт, кейс safety;
- любой сигнал — флаг правил или omni, метка или неуверенность классификатора, проверка
  не состоялась (AI недоступен), категория с `risk_level ≥ 1`, профиль, который всегда
  проверяет человек, — в очередь: контент ждёт решения; очередь — по самому строгому
  сигналу (P0 safety, P1 fraud, иначе P2 premod); уже видимый объект (сообщение чата) очередь
  скрывает только при признаке нарушения (`flagged`);
- иначе — публикация; у уровня 0 доля SAMPLE_RATE публикаций — ещё и в P2 после публикации.
"""

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.modules.moderation.domain.queues import Queue, stricter
from app.modules.moderation.domain.rules import (
    MatchSource,
    RuleAction,
    RuleCategory,
    RulesVerdict,
)
from app.platform.ai.port import ModerationResult, PolicyLabel, PolicyVerdict, Unavailable

CONFIDENT: Final = 0.8
"""Классификатору верим с этой уверенности **[Допущение]**: ниже — решает человек."""
SAMPLE_RATE: Final = 0.1
"""Доля публикаций уровня 0 на проверку после публикации (§14.1); флаг меняет её."""

LABEL_QUEUE: Final[Mapping[PolicyLabel, Queue]] = {
    PolicyLabel.DRUG_COURIER: Queue.SAFETY,
    PolicyLabel.SEXUAL_SERVICES: Queue.SAFETY,
    PolicyLabel.WEAPONS: Queue.SAFETY,
    PolicyLabel.PREPAYMENT_SCAM: Queue.FRAUD,
    PolicyLabel.OFF_PLATFORM_PAYMENT: Queue.FRAUD,
    PolicyLabel.MULE_RECRUITMENT: Queue.FRAUD,
}
"""Остальные метки (контакты, спам, «не заявка», вакансия) — P2."""

CATEGORY_LABEL: Final[Mapping[RuleCategory, PolicyLabel]] = {
    RuleCategory.DRUGS: PolicyLabel.DRUG_COURIER,
    RuleCategory.WEAPONS: PolicyLabel.WEAPONS,
    RuleCategory.ESCORT: PolicyLabel.SEXUAL_SERVICES,
    RuleCategory.SCAM: PolicyLabel.PREPAYMENT_SCAM,
    RuleCategory.MULE: PolicyLabel.MULE_RECRUITMENT,
    RuleCategory.CONTACTS: PolicyLabel.CONTACT_LEAK,
    RuleCategory.SPAM: PolicyLabel.SPAM_AD,
    RuleCategory.VACANCY: PolicyLabel.VACANCY,
}
"""Категория правила как метка политики: она же — код причины в решении и уведомлении."""


class Route(StrEnum):
    PUBLISH = "publish"
    REVIEW = "review"
    """В очередь: контент не публикуется до решения."""
    BLOCK = "block"
    """P0: скрыть, заморозить аккаунт, кейс safety."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Routing:
    route: Route
    queue: Queue | None = None
    """Очередь кейса: REVIEW, BLOCK и публикация на выборочную проверку."""
    reason_code: str | None = None
    """BLOCK: почему скрыто — причина заморозки и решения."""
    signals: tuple[str, ...] = ()
    """Что сработало — в доказательства кейса и журнал (без текста контента)."""
    post_review: bool = False
    """Опубликовано, но попало в выборочную проверку."""
    flagged: bool = False
    """REVIEW по признаку нарушения: видимый объект (сообщение чата) скрывается до решения."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Checks:
    rules: RulesVerdict
    omni: ModerationResult | Unavailable
    policy: PolicyVerdict | Unavailable | None
    """None — классификатор не звали: уровень доверия ≥ 1 и флагов нет."""
    always_review: bool = False
    risky_category: bool = False
    sampled: bool = False


def needs_classifier(*, trust_level: int, rules: RulesVerdict, omni: object) -> bool:
    """Классификатор — для уровня 0 и при любом флаге (§14.1)."""
    flagged = isinstance(omni, ModerationResult) and omni.flagged
    return trust_level == 0 or bool(rules.matches) or flagged


def route(checks: Checks) -> Routing:
    blocked = [m for m in checks.rules.matches if m.action is RuleAction.BLOCK]
    if blocked:
        label = CATEGORY_LABEL[blocked[0].category]
        return Routing(
            route=Route.BLOCK,
            queue=Queue.SAFETY,
            reason_code=label.value,
            signals=tuple(_rule_signals(checks.rules)),
        )
    found: list[tuple[Queue, str]] = [
        (_label_queue(CATEGORY_LABEL[match.category]), signal)
        for match, signal in zip(checks.rules.matches, _rule_signals(checks.rules), strict=True)
    ]
    match checks.omni:
        case Unavailable(reason=reason):
            found.append((Queue.PREMOD, f"omni:unavailable:{reason.value}"))
        case ModerationResult(flagged=True, scores=scores):
            found.append((Queue.PREMOD, f"omni:{_top(scores)}"))
    match checks.policy:
        case Unavailable(reason=reason):
            found.append((Queue.PREMOD, f"classifier:unavailable:{reason.value}"))
        case PolicyVerdict(label=label, confidence=confidence) if label is not PolicyLabel.OK:
            found.append((_label_queue(label), f"classifier:{label.value}:{confidence:.2f}"))
        case PolicyVerdict(confidence=confidence) if confidence < CONFIDENT:
            found.append((Queue.PREMOD, f"classifier:unsure:{confidence:.2f}"))
    if checks.always_review:
        found.append((Queue.PREMOD, "always_review"))
    if checks.risky_category:
        found.append((Queue.PREMOD, "risky_category"))
    if found:
        queue = Queue.PREMOD
        for candidate, _ in found:
            queue = stricter(candidate, queue)
        return Routing(
            route=Route.REVIEW,
            queue=queue,
            signals=tuple(s for _, s in found),
            flagged=_flagged(checks),
        )
    if checks.sampled:
        return Routing(
            route=Route.PUBLISH, queue=Queue.PREMOD, signals=("sample",), post_review=True
        )
    return Routing(route=Route.PUBLISH)


def _flagged(checks: Checks) -> bool:
    """Признак нарушения: слово словаря или velocity, флаг omni, метка классификатора. Контакты
    (детектор, правило или метка), детектор предоплаты, недоступный AI и сомнение классификатора —
    повод показать человеку, но не нарушение: в переписке контакты скрывает маскирование, о
    предоплате предупреждает памятка (6.3a)."""
    rules = any(
        match.source is not MatchSource.DETECTOR and match.category is not RuleCategory.CONTACTS
        for match in checks.rules.matches
    )
    omni = isinstance(checks.omni, ModerationResult) and checks.omni.flagged
    policy = isinstance(checks.policy, PolicyVerdict) and checks.policy.label not in _NOT_VIOLATIONS
    return rules or omni or policy


_NOT_VIOLATIONS: Final = frozenset({PolicyLabel.OK, PolicyLabel.CONTACT_LEAK})


def sampled(entity_id: UUID, rate: float) -> bool:
    """Попал ли объект в выборку: одинаково при повторе задачи и в любом процессе."""
    digest = hashlib.sha256(entity_id.bytes).digest()
    return int.from_bytes(digest[:4]) / 2**32 < rate


def _label_queue(label: PolicyLabel) -> Queue:
    return LABEL_QUEUE.get(label, Queue.PREMOD)


def _rule_signals(verdict: RulesVerdict) -> Iterable[str]:
    """Слово словаря, вид контакта или правило velocity — не текст пользователя."""
    for match in verdict.matches:
        yield f"{match.source.value}:{match.category.value}:{match.action.value}:{match.evidence}"


def _top(scores: Mapping[str, float]) -> str:
    return max(scores, key=scores.__getitem__) if scores else "flagged"
