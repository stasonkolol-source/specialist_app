"""RED-метрики API (DEVELOPMENT_PLAN 3.3): шаблон маршрута вместо пути, /up без метрик.

Настройки указывают на адреса, где никто не слушает: метрики не ходят в БД.
"""

import pytest
from fastapi import HTTPException
from prometheus_client import CollectorRegistry

from app.platform.settings import Settings
from tests.plugins.http import http_app, sample_router

pytestmark = pytest.mark.unit

router = sample_router()


@router.get("/items/{item_id}")
async def read_item(item_id: str) -> dict[str, str]:
    if item_id == "gone":
        raise HTTPException(status_code=404)
    return {"id": item_id}


ROUTE = "/api/v1/test/items/{item_id}"


async def test_requests_are_counted_by_route_template_not_raw_path(
    offline_settings: Settings,
) -> None:
    async with http_app(offline_settings, router) as app:
        for item in ("8d1f2c", "+381641234567", "gone"):
            await app.client.get(f"/api/v1/test/items/{item}")
        await app.client.get("/api/v1/no-such-route/42")
        await app.client.get("/up")
        registry = await app.container.get(CollectorRegistry)

    def count(route: str, status_class: str) -> float | None:
        labels = {"method": "GET", "route": route, "status_class": status_class}
        return registry.get_sample_value("http_requests_total", labels)

    assert count(ROUTE, "2xx") == 2
    assert count(ROUTE, "4xx") == 1
    assert count("<unmatched>", "4xx") == 1
    observed = registry.get_sample_value(
        "http_request_duration_seconds_count", {"method": "GET", "route": ROUTE}
    )
    assert observed == 3
    exported = "\n".join(
        f"{sample.labels}" for metric in registry.collect() for sample in metric.samples
    )
    assert "+381641234567" not in exported
    assert "/up" not in exported  # healthcheck прокси — не трафик API
