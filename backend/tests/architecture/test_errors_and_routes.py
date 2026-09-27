"""Ошибки и маршруты по одним правилам (ADR-0020 §9, §10).

- Каждая доменная ошибка наследует класс из таблицы §9 — иначе HTTP вернул бы 500.
- `code` задан в самом классе, в snake_case и уникален на проект.
- operationId — `<модуль>_<функция>`, уникален; обработчики живут только в http-слое.
"""

import importlib
import pkgutil
import re
from collections.abc import Iterator

import pytest

import app
from app.entrypoints._wiring import make_web_container, module_routers
from app.interfaces.http.app import create_app
from app.interfaces.http.errors import (
    HTTP_CODES,
    INTERNAL_ERROR,
    MALFORMED_REQUEST,
    VALIDATION_ERROR,
    status_for,
)
from app.interfaces.http.middleware import (
    CLIENT_UPGRADE_REQUIRED,
    INVALID_CLIENT_HEADER,
    MAINTENANCE,
)
from app.platform.i18n.catalogs import COMPLETE, catalog_path, read_catalog
from app.platform.kernel.errors import DomainError
from app.platform.settings import Settings

pytestmark = pytest.mark.unit

HTTP_ONLY_CODES = {
    INTERNAL_ERROR,
    MALFORMED_REQUEST,
    VALIDATION_ERROR,
    CLIENT_UPGRADE_REQUIRED,
    INVALID_CLIENT_HEADER,
    MAINTENANCE,
}
_CODE = re.compile(r"[a-z][a-z0-9_]*")
_OPERATION_ID = re.compile(r"[a-z][a-z_]*_[a-z][a-z0-9_]*")


def _import_all() -> None:
    for info in pkgutil.walk_packages(app.__path__, prefix="app."):
        if ".tests" in info.name or info.name.endswith(".__main__"):
            continue
        importlib.import_module(info.name)


def _subclasses(cls: type[DomainError]) -> Iterator[type[DomainError]]:
    for sub in cls.__subclasses__():
        if sub.__module__.startswith("app."):
            yield sub
        yield from _subclasses(sub)


@pytest.fixture(scope="module")
def domain_errors() -> list[type[DomainError]]:
    _import_all()
    return sorted(set(_subclasses(DomainError)), key=lambda c: f"{c.__module__}.{c.__qualname__}")


def test_every_domain_error_has_an_http_status(domain_errors: list[type[DomainError]]) -> None:
    orphans = [f"{c.__module__}.{c.__qualname__}" for c in domain_errors if status_for(c) is None]
    assert orphans == []


def test_error_codes_are_own_snake_case_and_unique(domain_errors: list[type[DomainError]]) -> None:
    seen: dict[str, str] = {}
    for cls in domain_errors:
        name = f"{cls.__module__}.{cls.__qualname__}"
        assert "code" in cls.__dict__, f"{name}: code must be declared in the class itself"
        assert _CODE.fullmatch(cls.code), f"{name}: code {cls.code!r} is not snake_case"
        assert cls.code not in seen, f"{name}: code {cls.code!r} is taken by {seen[cls.code]}"
        seen[cls.code] = name


def test_every_error_code_has_text_in_complete_catalogs(
    domain_errors: list[type[DomainError]],
) -> None:
    """Ключ `errors.<code>` есть в ru и sr_Cyrl для доменных и HTTP-кодов (ADR-0020 §15)."""
    codes = {cls.code for cls in domain_errors} | set(HTTP_CODES.values()) | HTTP_ONLY_CODES
    for locale in COMPLETE:
        keys = set(read_catalog(catalog_path(locale)))
        assert sorted(code for code in codes if f"errors.{code}" not in keys) == [], locale


async def test_operation_ids_follow_the_rule(offline_settings: Settings) -> None:
    container = make_web_container(offline_settings)
    try:
        spec = create_app(container, offline_settings, module_routers()).openapi()
    finally:
        await container.close()
    ids = [op["operationId"] for path in spec.get("paths", {}).values() for op in path.values()]
    assert [i for i in ids if not _OPERATION_ID.fullmatch(i)] == []
    assert len(ids) == len(set(ids))
