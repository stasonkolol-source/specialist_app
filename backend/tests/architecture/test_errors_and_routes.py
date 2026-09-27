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
from app.interfaces.http.errors import status_for
from app.platform.kernel.errors import DomainError
from app.platform.settings import Settings

pytestmark = pytest.mark.unit

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


async def test_operation_ids_follow_the_rule(offline_settings: Settings) -> None:
    container = make_web_container(offline_settings)
    try:
        spec = create_app(container, offline_settings, module_routers()).openapi()
    finally:
        await container.close()
    ids = [op["operationId"] for path in spec.get("paths", {}).values() for op in path.values()]
    assert [i for i in ids if not _OPERATION_ID.fullmatch(i)] == []
    assert len(ids) == len(set(ids))
