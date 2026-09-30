"""Предохранитель внешнего AI (circuit breaker, ADR-0016 §3, ARCHITECTURE §12.4).

После THRESHOLD сбоев подряд провайдер COOLDOWN не вызывается вовсе: контент сразу уходит в
ручную очередь, а не ждёт таймаутов каждой проверки. После паузы пропускается одна пробная
проверка: удалась — предохранитель закрыт; не удалась или потерялась (отмена, неожиданная
ошибка) — следующая пробная ещё через COOLDOWN. Время — монотонное: перевод часов не
открывает и не закрывает предохранитель. Состояние — в процессе: у каждого воркера своё, и
это достаточно (провайдер общий, сбой увидят все).
"""

import time
from collections.abc import Callable
from datetime import timedelta

THRESHOLD = 5
COOLDOWN = timedelta(seconds=60)


class CircuitBreaker:
    def __init__(
        self,
        *,
        threshold: int = THRESHOLD,
        cooldown: timedelta = COOLDOWN,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold, self._cooldown = threshold, cooldown.total_seconds()
        self._monotonic = monotonic
        self._failures = 0
        self._opened_at: float | None = None

    def allow(self) -> bool:
        """Можно ли звать провайдера сейчас."""
        if self._opened_at is None:
            return True
        now = self._monotonic()
        if now - self._opened_at < self._cooldown:
            return False
        self._opened_at = now  # пробная проверка; остальные ждут её исхода или новой паузы
        return True

    def success(self) -> None:
        self._failures, self._opened_at = 0, None

    def failure(self) -> None:
        self._failures += 1
        if self._opened_at is not None or self._failures >= self._threshold:
            self._opened_at = self._monotonic()

    @property
    def open(self) -> bool:
        return self._opened_at is not None
