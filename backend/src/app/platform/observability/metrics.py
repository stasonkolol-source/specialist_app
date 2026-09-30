"""Метрики Prometheus: реестр процесса. Счётчики добавляют шаги по мере появления (0.13, 3.3).

Экспорт наружу (`/metrics`, Grafana Alloy) — шаг 3.3; пока метрики живут в реестре
процесса, а превышения порогов пишутся в лог.
"""

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Gauge


def make_registry() -> CollectorRegistry:
    """Отдельный реестр процесса — без глобального состояния модуля (ADR-0020 §7)."""
    return CollectorRegistry(auto_describe=True)


@dataclass(frozen=True, slots=True)
class QueueMetrics:
    lag: Gauge
    """Сколько ждёт самая старая готовая к запуску задача очереди, секунды."""


def make_queue_metrics(registry: CollectorRegistry) -> QueueMetrics:
    return QueueMetrics(
        lag=Gauge(
            "procrastinate_queue_lag_seconds",
            "Age of the oldest runnable job in the queue",
            ["queue"],
            registry=registry,
        )
    )
