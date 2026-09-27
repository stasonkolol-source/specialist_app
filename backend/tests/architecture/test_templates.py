"""Шаблоны copier дают код по правилам ADR-0020 (§12): модуль со слоями, use case с командой.

Полная проверка — `make new-module NAME=tmp_check && make check`; здесь — быстрый рендер
во временный каталог, чтобы шаблон не устаревал незаметно.
"""

import ast
from pathlib import Path

import pytest
from copier import run_copy

from tests.architecture.test_code_rules import REQUIRED, REQUIRED_TESTS

pytestmark = pytest.mark.unit

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"


def _python_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def test_module_template_renders_required_layers(tmp_path: Path) -> None:
    run_copy(
        str(TEMPLATES / "module"),
        str(tmp_path),
        data={"name": "lost_found"},
        defaults=True,
        quiet=True,
    )
    module = tmp_path / "lost_found"
    assert [name for name in (*REQUIRED, *REQUIRED_TESTS) if not (module / name).exists()] == []
    for path in _python_files(module):
        ast.parse(path.read_text(encoding="utf-8"))
    assert "class LostFoundProvider(Provider)" in (module / "di.py").read_text(encoding="utf-8")
    assert list(tmp_path.glob(".copier-answers*")) == []


def test_use_case_template_renders_class_command_and_test(tmp_path: Path) -> None:
    run_copy(
        str(TEMPLATES / "use_case"),
        str(tmp_path),
        data={"module": "jobs", "name": "close_job"},
        defaults=True,
        quiet=True,
    )
    base = tmp_path / "src" / "app" / "modules" / "jobs"
    use_case = ast.parse(
        (base / "application" / "use_cases" / "close_job.py").read_text(encoding="utf-8")
    )
    classes = {node.name for node in use_case.body if isinstance(node, ast.ClassDef)}
    assert classes == {"CloseJob", "CloseJobCommand"}
    test = (base / "tests" / "integration" / "test_close_job.py").read_text(encoding="utf-8")
    assert "async def test_close_job(" in test
    assert "pytest.mark.integration" in test


@pytest.mark.parametrize("name", ["Jobs", "1jobs", "jobs-x", "_jobs"])
def test_module_template_rejects_bad_names(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 — copier бросает ValueError валидатора
        run_copy(
            str(TEMPLATES / "module"), str(tmp_path), data={"name": name}, defaults=True, quiet=True
        )
