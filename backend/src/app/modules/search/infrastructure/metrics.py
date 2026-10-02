"""Метрики поиска (Prometheus): лаг read-model — от события до новой строки (4.1)."""

from prometheus_client import CollectorRegistry, Histogram

LAG_BUCKETS = (0.1, 0.5, 1, 2, 5, 10, 30, 60, 300)


class PrometheusIndexMetrics:
    def __init__(self, registry: CollectorRegistry) -> None:
        self._lag = Histogram(
            "search_index_lag_seconds",
            "Delay from a source event to the rebuilt search read-model row",
            buckets=LAG_BUCKETS,
            registry=registry,
        )

    def observe_lag(self, seconds: float) -> None:
        self._lag.observe(max(seconds, 0.0))
