"""Метрики модерации (Prometheus): маршруты автопроверки — доля контента в очереди (2.6)."""

from prometheus_client import CollectorRegistry, Counter

from app.modules.moderation.domain.cases import EntityType
from app.modules.moderation.domain.pipeline import Route


class PrometheusAutoCheckMetrics:
    def __init__(self, registry: CollectorRegistry) -> None:
        self._checks = Counter(
            "moderation_auto_checks",
            "Content routed by the auto-moderation pipeline",
            ["entity_type", "route"],
            registry=registry,
        )

    def observe(self, entity_type: EntityType, route: Route) -> None:
        self._checks.labels(entity_type=entity_type.value, route=route.value).inc()
