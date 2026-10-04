"""Подписки на заявки: что видит S18 и кому уходит новая заявка (DEVELOPMENT_PLAN 5.7; §9.6).

Матчинг — SQL §9.6 (infrastructure/alerts.py); здесь — что с его результатом делает
`jobs.match_alerts`: одному человеку — одна карточка, даже если подошли две его подписки
(«сразу» важнее «подборкой»); заблокированные клиентом и в обратную сторону, удалённые и те, кому
санкция запрещает откликаться, — ничего. Лимит частоты: больше INSTANT_PER_HOUR карточек за час
или INSTANT_PER_DAY за сутки не присылаем — остальное уйдёт подборкой, а не потеряется.
"""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Final

from app.modules.jobs.domain.alert import AlertDelivery, AlertId, JobAlert
from app.modules.jobs.domain.job import JobId
from app.platform.kernel.ids import UserId

INSTANT_PER_HOUR: Final = 10
INSTANT_PER_DAY: Final = 40
"""Карточек B1 одному человеку: сверх — подборкой. Сотня карточек в день — повод заблокировать
бота, а с ним — и сообщения чата (§11.3)."""
DISTANCE_STEP_M: Final = 100


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertItem:
    """Строка S18: подписка и сколько заявок ей подошло за неделю."""

    alert: JobAlert
    week_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertCandidate:
    """Подписка, которой подошла заявка (строка SQL §9.6), — по порядку создания подписок."""

    alert_id: AlertId
    user_id: UserId
    delivery: AlertDelivery
    distance_m: float | None
    """От точки подписки до смещённой точки заявки; у подписки без радиуса — нет."""


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertMatch:
    """Кому и как уходит заявка: одна строка на человека."""

    user_id: UserId
    alert_id: AlertId
    delivery: AlertDelivery
    distance_m: int | None


@dataclass(frozen=True, slots=True, kw_only=True)
class RecentCards:
    """Сколько карточек B1 человек получил за час и за сутки — лимит частоты."""

    hour: int
    day: int


@dataclass(frozen=True, slots=True, kw_only=True)
class PendingDigest:
    """Заявка ждёт подборки получателя."""

    user_id: UserId
    alert_id: AlertId
    job_id: JobId


def route_matches(
    candidates: Iterable[AlertCandidate],
    *,
    excluded: Collection[UserId],
    recent: Mapping[UserId, RecentCards],
) -> list[AlertMatch]:
    """По карточке на человека: первая его подписка «сразу», иначе первая «подборкой»; сверх
    лимита частоты — подборкой."""
    chosen: dict[UserId, AlertCandidate] = {}
    for candidate in candidates:
        if candidate.user_id in excluded:
            continue
        current = chosen.get(candidate.user_id)
        if current is None or (
            current.delivery is AlertDelivery.DIGEST and candidate.delivery is AlertDelivery.INSTANT
        ):
            chosen[candidate.user_id] = candidate
    matches = []
    for candidate in chosen.values():
        delivery = candidate.delivery
        cards = recent.get(candidate.user_id)
        if (
            delivery is AlertDelivery.INSTANT
            and cards is not None
            and (cards.hour >= INSTANT_PER_HOUR or cards.day >= INSTANT_PER_DAY)
        ):
            delivery = AlertDelivery.DIGEST
        matches.append(
            AlertMatch(
                user_id=candidate.user_id,
                alert_id=candidate.alert_id,
                delivery=delivery,
                distance_m=_rounded(candidate.distance_m),
            )
        )
    return matches


def _rounded(distance: float | None) -> int | None:
    """Шагом 100 м: точку заявки и так сместили на 300–500 м."""
    if distance is None:
        return None
    return max(DISTANCE_STEP_M, round(distance / DISTANCE_STEP_M) * DISTANCE_STEP_M)
