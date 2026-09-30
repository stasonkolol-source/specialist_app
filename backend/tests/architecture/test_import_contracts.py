"""Контракты import-linter действительно ловят нарушения (ADR-0020 §1, §15).

Каждый тест копирует пакет `app` во временный каталог, добавляет одно намеренное
нарушение и проверяет, что `lint-imports` падает именно на нужном контракте.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
LINT_IMPORTS = Path(sys.executable).parent / "lint-imports"

pytestmark = pytest.mark.unit


def _run_lint_imports(src_root: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(src_root)}
    return subprocess.run(
        [str(LINT_IMPORTS), "--config", str(BACKEND / ".importlinter"), "--no-cache"],
        cwd=src_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """Копия исходников, в которую тест вносит одно нарушение."""
    shutil.copytree(BACKEND / "src" / "app", tmp_path / "app")
    return tmp_path


def _inject(sandbox: Path, relative: str, line: str) -> None:
    target = sandbox / "app" / relative
    target.write_text(target.read_text(encoding="utf-8") + f"\n{line}\n", encoding="utf-8")


def test_real_tree_keeps_all_contracts() -> None:
    result = _run_lint_imports(BACKEND / "src")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 broken" in result.stdout


def test_layer_violation_inside_module_is_caught(sandbox: Path) -> None:
    _inject(sandbox, "modules/jobs/domain/__init__.py", "import app.modules.jobs.application")
    result = _run_lint_imports(sandbox)
    assert result.returncode != 0
    assert "Слои внутри модуля (ADR-0020 §1) BROKEN" in result.stdout


def test_framework_import_in_domain_is_caught(sandbox: Path) -> None:
    _inject(sandbox, "modules/deals/domain/__init__.py", "import sqlalchemy")
    result = _run_lint_imports(sandbox)
    assert result.returncode != 0
    assert "domain, application и контракты без фреймворков (ADR-0020 §1) BROKEN" in result.stdout


def test_upward_module_dependency_is_caught(sandbox: Path) -> None:
    # deals стоит ниже jobs в графе — обращаться к jobs ему нельзя даже через api
    _inject(sandbox, "modules/deals/application/__init__.py", "import app.modules.jobs.api")
    result = _run_lint_imports(sandbox)
    assert result.returncode != 0
    assert "Граф зависимостей модулей (ARCHITECTURE §5.4, ADR-0002) BROKEN" in result.stdout


def test_messaging_cannot_use_moderation(sandbox: Path) -> None:
    # moderation выше messaging (§5.4): детектор контактов переписка берёт из platform/text
    _inject(
        sandbox, "modules/messaging/application/__init__.py", "import app.modules.moderation.api"
    )
    result = _run_lint_imports(sandbox)
    assert result.returncode != 0
    assert "Граф зависимостей модулей (ARCHITECTURE §5.4, ADR-0002) BROKEN" in result.stdout


def test_shared_text_kernel_stays_free_of_frameworks(sandbox: Path) -> None:
    _inject(sandbox, "platform/text/contact_masking.py", "import sqlalchemy")
    result = _run_lint_imports(sandbox)
    assert result.returncode != 0
    assert "domain, application и контракты без фреймворков (ADR-0020 §1) BROKEN" in result.stdout


def test_import_of_foreign_internals_is_caught(sandbox: Path) -> None:
    # jobs может обращаться к deals, но только через api
    _inject(sandbox, "modules/jobs/application/__init__.py", "import app.modules.deals.domain")
    result = _run_lint_imports(sandbox)
    assert result.returncode != 0
    assert "Снаружи модуля deals виден только api (ADR-0002) BROKEN" in result.stdout


def test_platform_cannot_import_modules(sandbox: Path) -> None:
    _inject(sandbox, "platform/kernel/__init__.py", "import app.modules.identity.api")
    result = _run_lint_imports(sandbox)
    assert result.returncode != 0
    assert "Граф зависимостей модулей (ARCHITECTURE §5.4, ADR-0002) BROKEN" in result.stdout


def test_interfaces_are_independent(sandbox: Path) -> None:
    _inject(sandbox, "interfaces/bot/__init__.py", "import app.interfaces.http")
    result = _run_lint_imports(sandbox)
    assert result.returncode != 0
    assert "Интерфейсы процессов не импортируют друг друга (ADR-0020 §7) BROKEN" in result.stdout
