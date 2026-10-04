"""Метрики Prometheus: реестр процесса, общие метрики и их экспорт (DEVELOPMENT_PLAN 3.3).

У каждого процесса (web, bot, worker, worker-media) свой реестр; Grafana Alloy читает его
с внутреннего порта METRICS_PORT (`metrics_server`), а не с порта API: kamal-proxy и
Cloudflare туда не ведут. web — один процесс uvicorn на контейнер, поэтому режим
multiprocess prometheus-client не нужен (entrypoints/web.py).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import structlog
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    disable_created_metrics,
    start_http_server,
)

from app.platform.settings import MetricsSettings

log = structlog.get_logger(__name__)

HTTP_BUCKETS = (0.025, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.4, 0.6, 1.0, 2.5, 10.0)
"""Границы под SLO (ARCHITECTURE §16.5): p95 API < 150 мс, поиск p95 < 200 мс, critical
p95 > 300 мс, p99 < 400 мс — квантиль считается без интерполяции через эти пороги."""
HTTP_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
OTHER_METHOD = "OTHER"
"""Метод не из списка: метку не задаёт клиент — иначе каждый выдуманный метод стал бы рядом."""


def make_registry() -> CollectorRegistry:
    """Отдельный реестр процесса — без глобального состояния модуля (ADR-0020 §7)."""
    return CollectorRegistry(auto_describe=True)


@contextmanager
def metrics_server(settings: MetricsSettings, registry: CollectorRegistry) -> Iterator[None]:
    """Отдать реестр по HTTP на METRICS_HOST:METRICS_PORT, пока процесс работает.

    Сервер prometheus-client — в своём потоке: scrape не ждёт event loop процесса. Без порта
    (dev, тесты) не делает ничего. Занятый порт роняет старт: тихо пропавшие метрики хуже.
    """
    if settings.port is None:
        yield
        return
    # ряды *_created удвоили бы счётчики: в Grafana Cloud Free всего 10k активных рядов
    disable_created_metrics()  # type: ignore[no-untyped-call]  # функция без аннотаций
    server, thread = start_http_server(settings.port, addr=settings.host, registry=registry)
    log.info("metrics_server_started", host=settings.host, port=settings.port)
    try:
        yield
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


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


class HttpMetrics:
    """RED API: число запросов по классу статуса и длительность (без класса — меньше рядов).

    Маршрут — шаблон пути (`/api/v1/jobs/{job_id}`), а не сам путь: id и ПД в метки не идут.
    """

    def __init__(self, registry: CollectorRegistry) -> None:
        self._requests = Counter(
            "http_requests",
            "HTTP requests by method, route template and status class",
            ["method", "route", "status_class"],
            registry=registry,
        )
        self._duration = Histogram(
            "http_request_duration_seconds",
            "HTTP request duration by method and route template",
            ["method", "route"],
            buckets=HTTP_BUCKETS,
            registry=registry,
        )

    def observe(self, *, method: str, route: str, status: int, seconds: float) -> None:
        method = method if method in HTTP_METHODS else OTHER_METHOD
        self._requests.labels(method=method, route=route, status_class=f"{status // 100}xx").inc()
        self._duration.labels(method=method, route=route).observe(seconds)


class TelegramMetrics:
    """429 от Bot API (ARCHITECTURE §12.4): сколько раз и на сколько секунд Telegram
    останавливал отправку — по методу Bot API (`sendMessage`, `editMessageReplyMarkup`)."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self._flood_waits = Counter(
            "telegram_rate_limited",
            "Bot API calls answered 429 Too Many Requests",
            ["method"],
            registry=registry,
        )
        self._retry_after = Counter(
            "telegram_retry_after_seconds",
            "Sum of retry_after from Bot API 429 responses",
            ["method"],
            registry=registry,
        )

    def observe_flood_wait(self, *, method: str, retry_after: float) -> None:
        self._flood_waits.labels(method=method).inc()
        self._retry_after.labels(method=method).inc(max(retry_after, 0.0))
