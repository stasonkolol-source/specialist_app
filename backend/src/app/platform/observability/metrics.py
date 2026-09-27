"""Метрики Prometheus: реестр процесса. Счётчики добавляют шаги по мере появления (0.13, 3.3)."""

from prometheus_client import CollectorRegistry


def make_registry() -> CollectorRegistry:
    """Отдельный реестр процесса — без глобального состояния модуля (ADR-0020 §7)."""
    return CollectorRegistry(auto_describe=True)
