"""Скрипты владельца не печатают значения секретов (DEVELOPMENT_PLAN 0.4)."""

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
VALUE = "super-secret-value-123456"


def _run(*args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=SCRIPTS,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


def test_secret_writes_value_but_prints_only_name_and_length(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    result = _run(
        "secret.py", "SENTRY_DSN", "dev", "--stdin", "--file", str(target), stdin=VALUE + "\n"
    )
    assert result.returncode == 0, result.stderr
    assert VALUE not in result.stdout + result.stderr
    assert f"({len(VALUE)} chars)" in result.stdout
    assert target.read_text() == f"SENTRY_DSN={VALUE}\n"
    assert oct(target.stat().st_mode & 0o777) == "0o600"


def test_secret_rejects_quotes(tmp_path: Path) -> None:
    result = _run(
        "secret.py",
        "SENTRY_DSN",
        "dev",
        "--stdin",
        "--file",
        str(tmp_path / ".env"),
        stdin='"quoted"\n',
    )
    assert result.returncode == 1
    assert not (tmp_path / ".env").exists()


def test_secrets_check_prints_state_without_values(tmp_path: Path) -> None:
    example = tmp_path / ".env.example"
    env = tmp_path / ".env"
    example.write_text("SENTRY_DSN=\nAI_OPENAI_API_KEY=\n")
    env.write_text(f"SENTRY_DSN={VALUE}\n")
    result = _run("secrets_check.py", "--pair", str(example), str(env))
    assert result.returncode == 0, result.stderr
    assert VALUE not in result.stdout
    lines = {line.split()[0]: line.split()[-1] for line in result.stdout.splitlines()[1:]}
    assert lines["SENTRY_DSN"] == "задан"
    assert lines["AI_OPENAI_API_KEY"] == "пуст"
