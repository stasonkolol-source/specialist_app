"""Синглтоны — только через DI (ADR-0020 §7): никаких глобальных клиентов и скрытых синглтонов.

Запрещено на уровне модуля: engine, Valkey/Redis, aiogram Bot, клиенты S3, httpx, пул
psycopg, приложение Procrastinate. Запрещены и скрытые синглтоны: `@lru_cache`/`@cache` на
функции без аргументов, метакласс-синглтон, класс с `_instance`.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SRC = Path(__file__).resolve().parents[2] / "src" / "app"
CLIENT_FACTORIES = {
    "create_async_engine",
    "create_engine",
    "Redis",
    "from_url",
    "Bot",
    "client",
    "resource",
    "AsyncClient",
    "Client",
    "AsyncConnectionPool",
    "App",
    "PsycopgConnector",
}
CACHE_DECORATORS = {"lru_cache", "cache"}


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
    return None


def _violations(path: Path, root: Path = SRC) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in tree.body:  # только верхний уровень модуля
        values: list[ast.expr] = []
        if isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
            values.append(node.value)
        for value in values:
            name = _call_name(value)
            if name in CLIENT_FACTORIES:
                found.append(f"{path.relative_to(root)}:{node.lineno}: module-level {name}(...)")
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and not node.args.args:
            for deco in node.decorator_list:
                target = deco.func if isinstance(deco, ast.Call) else deco
                deco_name = (
                    target.attr
                    if isinstance(target, ast.Attribute)
                    else getattr(target, "id", None)
                )
                if deco_name in CACHE_DECORATORS:
                    found.append(
                        f"{path.relative_to(root)}:{node.lineno}: hidden singleton "
                        f"@{deco_name} on {node.name}()"
                    )
        if isinstance(node, ast.ClassDef):
            if "singleton" in node.name.lower():
                found.append(f"{path.relative_to(root)}:{node.lineno}: singleton class {node.name}")
            found.extend(
                f"{path.relative_to(root)}:{item.lineno}: {node.name}._instance"
                for item in node.body
                if isinstance(item, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "_instance" for t in item.targets)
            )
    return found


def test_no_global_clients_or_hidden_singletons() -> None:
    violations = [v for path in SRC.rglob("*.py") for v in _violations(path)]
    assert violations == [], "\n".join(violations)


def test_detector_catches_violations(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text(
        "from functools import lru_cache\n"
        "engine = create_async_engine('x')\n"
        "valkey = Redis.from_url('redis://')\n"
        "@lru_cache\n"
        "def get_bot(): ...\n"
        "class SingletonMeta(type): ...\n"
        "class Holder:\n"
        "    _instance = None\n"
    )
    assert len(_violations(bad, tmp_path)) == 5
