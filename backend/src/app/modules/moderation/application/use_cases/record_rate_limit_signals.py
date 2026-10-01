"""Сигналы риска по систематическим 429 (periodic `moderation.rate_limit_signals`, раз в
15 минут; ARCHITECTURE §13.3).

Счётчики превышений ведёт platform/ratelimit.py (0.13b): субъект за сутки UTC → лимит →
сколько 429. Задача читает вчера и сегодня (конец суток досчитывается после полуночи) и
пишет сигнал на каждый лимит, в который пользователь упёрся SYSTEMATIC_429 раз и больше, —
один раз за сутки (`dedupe_key`). Субъекты `ip:` пропускает адаптер: сигнал — о пользователе;
удалённых и неизвестных пользователей — use case.
"""

from dataclasses import dataclass
from datetime import timedelta

from app.modules.identity.api import IdentityApi
from app.modules.moderation.application.ports import RateLimitOverflows, RiskSignals
from app.modules.moderation.domain.risk import RiskSignal, rate_limit_signals
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordRateLimitSignalsCommand:
    days: int = 2
    """Сколько последних суток читать: сегодня и вчера (счётчики живут трое суток)."""


class RecordRateLimitSignals:
    def __init__(
        self,
        uow: UnitOfWork,
        overflows: RateLimitOverflows,
        signals: RiskSignals,
        identity: IdentityApi,
        clock: Clock,
    ) -> None:
        self._uow, self._overflows, self._signals = uow, overflows, signals
        self._identity, self._clock = identity, clock

    async def __call__(self, cmd: RecordRateLimitSignalsCommand) -> int:
        """Сколько новых сигналов записано."""
        today = self._clock.now().date()
        found: list[RiskSignal] = []
        for day in (today - timedelta(days=back) for back in reversed(range(cmd.days))):
            for user_id, exceeded in (await self._overflows.by_user(day)).items():
                found.extend(rate_limit_signals(user_id, day, exceeded))
        active = set()
        for user_id in {signal.user_id for signal in found}:
            user = await self._identity.get_user(user_id)
            if user is not None and not user.is_deleted:
                active.add(user_id)
        signals = [signal for signal in found if signal.user_id in active]
        if not signals:
            return 0
        async with self._uow:
            return await self._signals.add(signals)
