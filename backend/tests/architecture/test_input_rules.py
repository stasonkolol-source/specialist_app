"""Вход API по общим правилам (QA ADV-01, ADV-03, ADV-04; `platform/http/fields.py`).

- Каждое целое число на входе (путь, запрос, тело) — с верхней границей или из перечня: иначе
  2^31 в id справочника доходит до базы, и вместо 422 — 500 `integer out of range`.
- Каждая свободная строка тела Mini App — `CleanText`: NUL и невидимые символы вычищаются до
  проверок длины. Исключения — подписанные и служебные значения, их менять нельзя.
"""

from collections.abc import Iterator
from types import UnionType
from typing import Annotated, Any, Union, get_args, get_origin

import pytest
from fastapi.routing import APIRoute
from pydantic import BaseModel

from app.entrypoints._wiring import module_admin_routers, module_routers
from app.interfaces.http.admin_api import admin_openapi_spec
from app.interfaces.http.app import openapi_spec
from app.platform.http.fields import CleanText

pytestmark = pytest.mark.unit

CLEAN = get_args(CleanText)[1]
NOT_FREE_TEXT = {
    ("RefreshIn", "refresh_token"),  # токен: сверяется по хешу
    ("ConsentsIn", "terms_version"),  # версии сверяются с текущими
    ("ConsentsIn", "privacy_version"),
    ("UploadIn", "mime_type"),  # тип — из перечня назначения
    ("UploadedPartIn", "etag"),  # ETag хранилища: сверяет S3
    ("ContactShareIn", "init_data"),  # подписано Telegram: правка ломает подпись
    ("ContactShareIn", "contact"),
}


def _unbounded(spec: dict[str, Any]) -> Iterator[str]:
    schemas = spec.get("components", {}).get("schemas", {})

    def walk(schema: dict[str, Any], where: str, seen: frozenset[str]) -> Iterator[str]:
        if "$ref" in schema:
            name = schema["$ref"].rsplit("/", 1)[-1]
            if name not in seen:
                yield from walk(schemas[name], name, seen | {name})
            return
        if schema.get("type") == "integer" and "maximum" not in schema and "enum" not in schema:
            yield where
        for key in ("anyOf", "oneOf", "allOf"):
            for sub in schema.get(key, []):
                yield from walk(sub, where, seen)
        if "items" in schema:
            yield from walk(schema["items"], f"{where}[]", seen)
        for name, sub in schema.get("properties", {}).items():
            yield from walk(sub, f"{where}.{name}", seen)

    for path, item in spec.get("paths", {}).items():
        for method, operation in item.items():
            for param in operation.get("parameters", []):
                where = f"{method.upper()} {path} {param['name']}"
                yield from walk(param.get("schema", {}), where, frozenset())
            for content in operation.get("requestBody", {}).get("content", {}).values():
                yield from walk(content.get("schema", {}), f"{method.upper()} {path}", frozenset())


def test_every_integer_input_has_an_upper_bound() -> None:
    public = openapi_spec(module_routers())
    admin = admin_openapi_spec(module_admin_routers())
    assert sorted({*_unbounded(public), *_unbounded(admin)}) == []


def _strings(annotation: Any, cleaned: bool) -> Iterator[bool]:
    """Для каждой строки внутри аннотации — прошла ли она через `CleanText`."""
    origin = get_origin(annotation)
    if origin is Annotated:
        base, *metadata = get_args(annotation)
        yield from _strings(base, cleaned or CLEAN in metadata)
    elif origin in (Union, UnionType, list, tuple, set, frozenset):
        for arg in get_args(annotation):
            yield from _strings(arg, cleaned)
    elif annotation is str:
        yield cleaned


def _body_models() -> Iterator[type[BaseModel]]:
    seen: set[type[BaseModel]] = set()
    stack = [
        route.body_field.field_info.annotation
        for router in module_routers()
        for route in router.routes
        if isinstance(route, APIRoute) and route.body_field is not None
    ]
    while stack:
        model = stack.pop()
        if not isinstance(model, type) or not issubclass(model, BaseModel) or model in seen:
            continue
        seen.add(model)
        yield model
        for field in model.model_fields.values():
            stack.extend(_nested_models(field.annotation))


def _nested_models(annotation: Any) -> Iterator[Any]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        yield annotation
    for arg in get_args(annotation):
        yield from _nested_models(arg)


def test_free_text_in_request_bodies_is_cleaned() -> None:
    raw = [
        f"{model.__name__}.{name}"
        for model in _body_models()
        for name, field in model.model_fields.items()
        if (model.__name__, name) not in NOT_FREE_TEXT
        and not all(_strings(field.annotation, CLEAN in field.metadata))
    ]
    assert sorted(raw) == []
