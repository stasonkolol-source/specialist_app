"""Имена миграций: файл `<модуль>_NNNN_<slug>.py`, ревизия `<модуль>_NNNN` (ADR-0020 §10)."""

import ast
import re
from pathlib import Path

import pytest

from app.platform.db.registry import MODULE_SCHEMAS

pytestmark = pytest.mark.unit

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"
_FILE = re.compile(r"(?P<module>[a-z][a-z_]*?)_(?P<number>\d{4})_[a-z0-9_]+\.py")


def _revision(path: Path) -> object:
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.AnnAssign | ast.Assign):
            targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
            if any(isinstance(t, ast.Name) and t.id == "revision" for t in targets) and node.value:
                return ast.literal_eval(node.value)
    return None


@pytest.mark.parametrize("path", sorted(VERSIONS.glob("*.py")), ids=lambda p: p.name)
def test_migration_is_named_by_module(path: Path) -> None:
    match = _FILE.fullmatch(path.name)
    assert match, f"{path.name}: expected <module>_NNNN_<slug>.py"
    assert match["module"] in MODULE_SCHEMAS
    assert _revision(path) == f"{match['module']}_{match['number']}"
