"""operationId `<модуль>_<функция>` (ADR-0020 §10)."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.routing import APIRoute

from app.interfaces.http.operation_ids import operation_id

pytestmark = pytest.mark.unit


def _route(module: str, name: str = "close_job") -> APIRoute:
    async def endpoint() -> None: ...

    endpoint.__module__ = module
    endpoint.__name__ = name
    handler: Callable[..., Any] = endpoint
    return APIRoute("/x", handler, generate_unique_id_function=lambda route: "unused")


@pytest.mark.parametrize(
    ("module", "expected"),
    [
        ("app.modules.jobs.http.router", "jobs_close_job"),
        ("app.modules.jobs.http", "jobs_close_job"),
        ("app.modules.job_alerts.http.router", "job_alerts_close_job"),
        ("app.interfaces.http.views.specialist_card", "views_close_job"),
        ("app.interfaces.http.system", "system_close_job"),
    ],
)
def test_operation_id_is_owner_and_function(module: str, expected: str) -> None:
    assert operation_id(_route(module)) == expected


@pytest.mark.parametrize(
    "module", ["app.modules.jobs.application.use_cases", "app.modules.jobs.httpx", "tests.x"]
)
def test_handlers_outside_http_layer_are_rejected(module: str) -> None:
    with pytest.raises(ValueError, match="must live in"):
        operation_id(_route(module))
