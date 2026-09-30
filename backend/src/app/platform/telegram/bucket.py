"""Лимит скорости отправки (ARCHITECTURE §11.2): модель GCRA и её арифметика.

GCRA — тот же токен-бакет, записанный через «теоретическое время прихода» (TAT): сообщения
идут с интервалом `1 / rate`, разом — до `capacity`. Вместо «токена нет, попробуй позже»
лимитер резервирует точный слот: каждое сообщение знает, когда ему можно уйти, и слот уже
его. Поэтому очередь из тысяч уведомлений расходится по слотам за один проход, а не
перебирается заново каждую секунду.

В Valkey ту же арифметику атомарно считает Lua-скрипт лимитера (limiter.py): здесь — её
образец, который проверяют юнит-тесты, а скрипт — интеграционные на тех же сценариях.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Bucket:
    rate: float
    """Сообщений в секунду."""
    capacity: float
    """Сколько сообщений можно отправить разом после паузы."""

    @property
    def interval(self) -> float:
        return 1 / self.rate

    @property
    def tolerance(self) -> float:
        """Насколько раньше TAT можно отправить: это и даёт всплеск до `capacity`."""
        return (self.capacity - 1) * self.interval


def earliest(bucket: Bucket, tat: float | None, now: float) -> float:
    """Когда бакет пропустит следующее сообщение; TAT нет (давно не отправляли) — сейчас."""
    if tat is None:
        return now
    return max(now, tat - bucket.tolerance)


def advance(bucket: Bucket, tat: float | None, at: float) -> float:
    """TAT после сообщения, отправленного в `at`."""
    return max(tat if tat is not None else at, at) + bucket.interval
