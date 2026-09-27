"""Контракт OpenAPI 3.1 (DEVELOPMENT_PLAN 0.20, ARCHITECTURE §8.7, ADR-0003).

- Ошибки всех операций описаны ответом `default` с `application/problem+json` и схемой
  ProblemOut (RFC 9457, ADR-0020 §9): orval строит из неё тип ошибки api-client.
- `info.version` — версия контракта v1, а не релиз: иначе схема менялась бы каждый деплой.
- Схема выгружается в `backend/openapi.json` (`cli openapi`); CI сверяет файл с кодом.
"""

from datetime import datetime
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, ConfigDict

API_TITLE = "Соседи API"
API_VERSION = "1.0.0"
PROBLEM = "ProblemOut"


class FieldErrorOut(BaseModel):
    field: str
    code: str
    message: str


class ProblemOut(BaseModel):
    """Ошибка RFC 9457. Клиент ветвится по `code`, текст для человека — `detail`."""

    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    status: int
    code: str
    detail: str | None = None
    errors: list[FieldErrorOut] | None = None
    trace_id: str | None
    restriction: str | None = None
    """403 `restricted`: вид санкции."""
    until: datetime | None = None
    """403 `restricted`: до когда; null — бессрочно."""
    platform: str | None = None
    """426: платформа клиента из X-Client."""
    min_version: str | None = None
    """426: минимальная поддерживаемая версия клиента."""
    documents: list[str] | None = None
    """403 `consent_required`: документы без действующего согласия (`terms`, `privacy`,
    `age_18`)."""
    document: str | None = None
    """409 `legal_version_outdated`: документ, у которого сменилась версия."""
    current: str | None = None
    """409 `legal_version_outdated`: действующая версия документа."""


PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    "default": {"model": ProblemOut, "description": "Ошибка в формате RFC 9457"},
}


def install_openapi(app: FastAPI) -> None:
    """Схема приложения: `default`-ответы переводятся на application/problem+json."""

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            spec = get_openapi(
                title=API_TITLE,
                version=API_VERSION,
                openapi_version=app.openapi_version,
                routes=app.routes,
            )
            app.openapi_schema = _problem_json(spec)
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]  # штатный способ FastAPI


def _problem_json(spec: dict[str, Any]) -> dict[str, Any]:
    ref = {"$ref": f"#/components/schemas/{PROBLEM}"}
    for path in spec.get("paths", {}).values():
        for operation in path.values():
            default = operation.get("responses", {}).get("default")
            if default is not None:
                default["content"] = {"application/problem+json": {"schema": ref}}
    return spec
