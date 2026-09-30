"""Правила кода, которые не выразить в import-linter (ADR-0020 §14–15).

Разбор исходников через `ast`, без импорта: быстро и не зависит от побочных эффектов.
"""

import ast
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SRC = Path(__file__).resolve().parents[2] / "src" / "app"
MODULES = SRC / "modules"
STDLIB = frozenset(sys.stdlib_module_names)


def _files(*roots: Path) -> Iterator[Path]:
    for root in roots:
        paths = [root] if root.is_file() else sorted(root.rglob("*.py"))
        yield from (p for p in paths if "tests" not in p.relative_to(SRC).parts)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _rel(path: Path) -> str:
    return str(path.relative_to(SRC.parent))


def _module_parts(layer: str) -> list[Path]:
    return sorted(p for p in MODULES.glob(f"*/{layer}") if p.exists())


def _top_imports(tree: ast.Module) -> Iterator[tuple[int, str]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.lineno, node.module.split(".")[0]


# --- чистое ядро: разрешающий список (§15) ------------------------------------------------

PURE_CORE = [
    *_module_parts("domain"),
    *_module_parts("api.py"),
    *_module_parts("errors.py"),
    SRC / "platform" / "kernel",
    SRC / "platform" / "contracts",
    SRC / "platform" / "text",
    *sorted(SRC.glob("platform/*/port.py")),
]


@pytest.mark.parametrize(
    ("roots", "allowed"),
    [(PURE_CORE, frozenset()), (_module_parts("application"), frozenset({"structlog"}))],
    ids=["domain-api-errors-kernel-contracts-ports", "application"],
)
def test_core_imports_only_stdlib(roots: list[Path], allowed: frozenset[str]) -> None:
    bad = [
        f"{_rel(path)}:{line} imports {name}"
        for path in _files(*roots)
        for line, name in _top_imports(_tree(path))
        if name not in STDLIB and name != "app" and name not in allowed
    ]
    assert bad == []


# --- транзакции и конкурентность ----------------------------------------------------------


def _calls(tree: ast.Module) -> Iterator[ast.Call]:
    yield from (node for node in ast.walk(tree) if isinstance(node, ast.Call))


def _attr_name(call: ast.Call) -> str | None:
    return call.func.attr if isinstance(call.func, ast.Attribute) else None


def test_commit_and_rollback_only_in_platform_db() -> None:
    db = SRC / "platform" / "db"
    bad = [
        f"{_rel(path)}:{call.lineno} .{_attr_name(call)}()"
        for path in _files(SRC)
        if db not in path.parents
        for call in _calls(_tree(path))
        if _attr_name(call) in {"commit", "rollback"}
    ]
    assert bad == []


CONCURRENCY_FREE = [
    *_module_parts("application"),
    *_module_parts("http"),
    *_module_parts("bot"),
    *_module_parts("admin"),
    *_module_parts("tasks.py"),
    SRC / "interfaces" / "http" / "views",
]


def test_no_gather_or_task_group_over_one_session() -> None:
    """Одна сессия на скоуп не допускает параллельных запросов (§14)."""
    bad = [
        f"{_rel(path)}:{node.lineno}"
        for path in _files(*CONCURRENCY_FREE)
        for node in ast.walk(_tree(path))
        if (isinstance(node, ast.Attribute) and node.attr in {"gather", "TaskGroup"})
        or (isinstance(node, ast.Name) and node.id in {"gather", "TaskGroup"})
    ]
    assert bad == []


def test_no_asdict_unpacking_in_domain_and_application() -> None:
    bad = [
        f"{_rel(path)}:{call.lineno}"
        for path in _files(*_module_parts("domain"), *_module_parts("application"))
        for call in _calls(_tree(path))
        for keyword in call.keywords
        if keyword.arg is None
        and isinstance(keyword.value, ast.Call)
        and getattr(keyword.value.func, "id", getattr(keyword.value.func, "attr", None)) == "asdict"
    ]
    assert bad == []


# --- структура и имена --------------------------------------------------------------------

REQUIRED = (
    "__init__.py",
    "api.py",
    "errors.py",
    "di.py",
    "domain",
    "application",
    "infrastructure",
)
REQUIRED_TESTS = ("tests/__init__.py", "tests/unit", "tests/integration", "tests/api")
DUMPS = {"utils.py", "helpers.py", "common.py", "misc.py"}


def _modules() -> list[Path]:
    return sorted(p for p in MODULES.iterdir() if p.is_dir() and not p.name.startswith("__"))


@pytest.mark.parametrize("module", _modules(), ids=lambda p: p.name)
def test_module_has_required_layers(module: Path) -> None:
    missing = [name for name in (*REQUIRED, *REQUIRED_TESTS) if not (module / name).exists()]
    assert missing == []
    for layer in ("domain", "application", "infrastructure"):
        assert (module / layer / "__init__.py").exists(), f"{module.name}/{layer} is not a package"


def test_no_dump_modules() -> None:
    assert [_rel(p) for p in SRC.rglob("*.py") if p.name in DUMPS] == []


def _pascal(snake: str) -> str:
    return "".join(part.capitalize() for part in snake.split("_"))


def _classes(tree: ast.Module) -> dict[str, ast.ClassDef]:
    return {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}


def test_use_case_file_holds_its_class_and_command() -> None:
    bad = [
        f"{_rel(path)}: no class {expected}"
        for path in sorted(MODULES.glob("*/application/use_cases/*.py"))
        if path.name != "__init__.py"
        for expected in (_pascal(path.stem), f"{_pascal(path.stem)}Command")
        if expected not in _classes(_tree(path))
    ]
    assert bad == []


def test_orm_classes_are_named_row() -> None:
    bad = []
    for path in sorted(MODULES.glob("*/infrastructure/models.py")):
        for name, node in _classes(_tree(path)).items():
            is_table = any(
                isinstance(stmt, ast.Assign | ast.AnnAssign)
                and any(
                    isinstance(t, ast.Name) and t.id == "__tablename__"
                    for t in (stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target])
                )
                for stmt in node.body
            )
            if is_table and not name.endswith("Row"):
                bad.append(f"{_rel(path)}: {name}")
    assert bad == []


def test_module_task_names_start_with_module() -> None:
    """`TaskRef("<модуль>.<глагол>_<объект>", …)` в коде модуля (§10)."""
    bad = []
    for module in _modules():
        for path in _files(module):
            for call in _calls(_tree(path)):
                if getattr(call.func, "id", None) != "TaskRef" or not call.args:
                    continue
                first = call.args[0]
                name = first.value if isinstance(first, ast.Constant) else None
                if not isinstance(name, str) or not name.startswith(f"{module.name}."):
                    bad.append(f"{_rel(path)}:{call.lineno} {name!r}")
    assert bad == []
