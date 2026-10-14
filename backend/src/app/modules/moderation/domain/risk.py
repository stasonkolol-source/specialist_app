"""Сигналы риска (ARCHITECTURE §13.3, §7.3 `moderation.risk_signals`).

Сигнал — факт о пользователе для уровня доверия, антиспама и антифрода: систематические
429, подтверждённая жалоба, контакты и предоплата в тексте (2.6), повторная регистрация
после удаления (2.12). Один и тот же факт пишется один раз (`dedupe_key`).

Просьба о предоплате (`content_signals`) — сигнал на каждый объект, где её нашёл детектор:
сообщение, заявка, отклик, профиль; контакты — только в сообщении чата (в профиле и заявке их
решает модерация), с половинным весом. Карточка кейса показывает сигналы за RISK_WINDOW
(`summarize`) и при повторе просьбы у новичка предлагает тяжесть (`suggested_severity`) — только
предлагает: ошибка детектора дороже часа модератора, автосанкций нет.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.modules.moderation.domain.cases import EntityType
from app.modules.moderation.domain.pipeline import CONTACTS_SIGNAL, PREPAYMENT_SIGNAL
from app.modules.moderation.domain.sanctions import Severity
from app.platform.kernel.ids import UserId


class RiskSignalKind(StrEnum):
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    REPORT_CONFIRMED = "report_confirmed"
    CONTACT_LEAK = "contact_leak"
    PREPAYMENT_REQUEST = "prepayment_request"
    REREGISTERED_AFTER_DELETION = "reregistered_after_deletion"


SYSTEMATIC_429: Final = 5
"""Сколько 429 одного лимита за сутки — уже система, а не случайность **[Допущение]**:
человек, который упёрся в лимит, отступает после двух-трёх ответов, скрипт — нет."""
CONTACT_LEAK_WEIGHT: Final = 0.5
"""Контакты в чате до договорённости: их и так скрывает маскирование, вес вдвое меньше."""
RISK_WINDOW: Final = timedelta(days=30)
"""Сигналы за это время — в карточке кейса и в счёте повторов."""
REPEAT_REQUESTS: Final = 2
"""Столько просьб о предоплате за RISK_WINDOW у аккаунта уровня ≤ REPEAT_TRUST_LEVEL — повтор:
карточка предлагает серьёзное нарушение (приостановка до проверки) **[Допущение]**."""
REPEAT_TRUST_LEVEL: Final = 1


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskSignal:
    user_id: UserId
    kind: RiskSignalKind
    weight: float = 1.0
    ref_type: str | None = None
    ref_id: UUID | None = None
    details: Mapping[str, object] = field(default_factory=dict)
    dedupe_key: str | None = None
    """Один факт — один сигнал: повтор с тем же ключом не пишется."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskSummary:
    """Сигналы одного вида за окно — строкой карточки: «предоплата ×2»."""

    kind: RiskSignalKind
    count: int
    weight: float
    with_sanctions: bool = False
    """Пере-регистрация после удаления аккаунта с санкциями (record_reregistration)."""


def rate_limit_signals(user_id: UserId, day: date, exceeded: Mapping[str, int]) -> list[RiskSignal]:
    """Сигнал на каждый лимит, в который пользователь упёрся систематически за `day` (UTC)."""
    return [
        RiskSignal(
            user_id=user_id,
            kind=RiskSignalKind.RATE_LIMIT_EXCEEDED,
            details={"rate": rate, "count": count, "day": day.isoformat()},
            dedupe_key=f"{RiskSignalKind.RATE_LIMIT_EXCEEDED}:{day:%Y%m%d}:{rate}:{user_id}",
        )
        for rate, count in sorted(exceeded.items())
        if count >= SYSTEMATIC_429
    ]


def content_signals(
    *, author_id: UserId, entity_type: EntityType, entity_id: UUID, signals: Sequence[str]
) -> list[RiskSignal]:
    """Сигналы по итогу автопроверки объекта (`Routing.signals`): просьба о предоплате — у любого
    объекта, контакты — в сообщении чата. Один объект — один сигнал каждого вида: повтор
    проверки (правка, повтор задачи) ничего не добавляет."""
    found: list[RiskSignal] = []
    if PREPAYMENT_SIGNAL in signals:
        found.append(
            _content_signal(author_id, RiskSignalKind.PREPAYMENT_REQUEST, entity_type, entity_id)
        )
    if entity_type is EntityType.MESSAGE and any(s.startswith(CONTACTS_SIGNAL) for s in signals):
        found.append(
            _content_signal(
                author_id,
                RiskSignalKind.CONTACT_LEAK,
                entity_type,
                entity_id,
                weight=CONTACT_LEAK_WEIGHT,
            )
        )
    return found


def _content_signal(
    author_id: UserId,
    kind: RiskSignalKind,
    entity_type: EntityType,
    entity_id: UUID,
    *,
    weight: float = 1.0,
) -> RiskSignal:
    return RiskSignal(
        user_id=author_id,
        kind=kind,
        weight=weight,
        ref_type=entity_type.value,
        ref_id=entity_id,
        dedupe_key=f"{kind}:{entity_type.value}:{entity_id}",
    )


def summarize(signals: Iterable[RiskSignal]) -> tuple[RiskSummary, ...]:
    """Сигналы по видам, в порядке первого появления: число, суммарный вес, были ли санкции
    у прежнего аккаунта."""
    found: dict[RiskSignalKind, RiskSummary] = {}
    for signal in signals:
        current = found.get(signal.kind)
        sanctioned = bool(signal.details.get("had_sanctions"))
        found[signal.kind] = RiskSummary(
            kind=signal.kind,
            count=(current.count if current else 0) + 1,
            weight=(current.weight if current else 0.0) + signal.weight,
            with_sanctions=(current.with_sanctions if current else False) or sanctioned,
        )
    return tuple(found.values())


def prepayment_requests(summaries: Iterable[RiskSummary]) -> int:
    """Сколько просьб о предоплате среди сигналов окна."""
    return sum(s.count for s in summaries if s.kind is RiskSignalKind.PREPAYMENT_REQUEST)


def suggested_severity(
    summaries: Iterable[RiskSummary], *, trust_level: int | None
) -> Severity | None:
    """Повтор просьбы о предоплате у новичка — предлагаемая тяжесть: серьёзное (приостановка до
    проверки). Решает модератор: автосанкций по детектору нет."""
    if trust_level is None or trust_level > REPEAT_TRUST_LEVEL:
        return None
    return Severity.SERIOUS if prepayment_requests(summaries) >= REPEAT_REQUESTS else None
