"""Скрипты владельца не печатают значения секретов (DEVELOPMENT_PLAN 0.4)."""

import json
import re
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


def _fake_gh(tmp_path: Path, *, fails: bool = False) -> tuple[Path, Path]:
    """gh, который записывает аргументы и stdin вместо GitHub (0.25c, Q1(б))."""
    log = tmp_path / "gh.json"
    gh = tmp_path / "gh"
    gh.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "call = {'args': sys.argv[1:], 'stdin': sys.stdin.read()}\n"
        f"open({str(log)!r}, 'w').write(json.dumps(call))\n"
        f"sys.exit({1 if fails else 0})\n"
    )
    gh.chmod(0o755)
    return gh, log


def test_secret_for_stage_goes_to_github_through_stdin(tmp_path: Path) -> None:
    gh, log = _fake_gh(tmp_path)
    result = _run(
        "secret.py", "S3_ACCESS_KEY_ID", "stage", "--stdin", "--gh", str(gh), stdin=VALUE + "\n"
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(log.read_text()) == {
        "args": ["secret", "set", "S3_ACCESS_KEY_ID", "--env", "stage"],
        "stdin": VALUE,  # не --body: значение не попадает в историю shell и список процессов
    }
    assert VALUE not in result.stdout + result.stderr
    assert result.stdout == (
        f"secret: S3_ACCESS_KEY_ID set ({len(VALUE)} chars) in GitHub environment stage\n"
    )


def test_secret_reports_a_failed_gh(tmp_path: Path) -> None:
    gh, _ = _fake_gh(tmp_path, fails=True)
    result = _run(
        "secret.py", "S3_ACCESS_KEY_ID", "production", "--stdin", "--gh", str(gh), stdin=VALUE
    )
    assert result.returncode == 1
    assert "gh secret set" in result.stderr
    assert "set (" not in result.stdout


def test_gen_secret_without_name_only_prints_a_value() -> None:
    first, second = _run("gen_secret.py"), _run("gen_secret.py")
    assert first.returncode == second.returncode == 0
    assert re.fullmatch(r"[0-9a-f]{64}\n", first.stdout)
    assert first.stdout != second.stdout


def test_gen_secret_shows_once_then_sends_to_github_and_clears(tmp_path: Path) -> None:
    gh, log = _fake_gh(tmp_path)
    result = _run("gen_secret.py", "APP_DB_PASSWORD", "stage", "--gh", str(gh), stdin="\n")
    assert result.returncode == 0, result.stderr
    sent = json.loads(log.read_text())
    assert sent["args"] == ["secret", "set", "APP_DB_PASSWORD", "--env", "stage"]
    value = sent["stdin"]
    assert re.fullmatch(r"[0-9a-f]{64}", value)
    assert result.stdout.count(value) == 1
    # после Enter экран и прокрутка стёрты, дальше значение не печатается
    assert result.stdout.index("\033[2J\033[3J\033[H") > result.stdout.index(value)
    assert result.stdout.endswith("set (64 chars) in GitHub environment stage\n")


def test_gen_secret_cancelled_sends_nothing(tmp_path: Path) -> None:
    gh, log = _fake_gh(tmp_path)
    result = _run("gen_secret.py", "APP_HASH_KEY", "production", "--gh", str(gh), stdin="")
    assert result.returncode == 1
    assert "ничего не записано" in result.stderr
    assert not log.exists()


@pytest.mark.parametrize("name", ["JWT_KEYS", "DEPLOY_SSH_KEY"])
def test_gen_secret_points_keys_to_their_own_tools(name: str) -> None:
    result = _run("gen_secret.py", name, "stage")
    assert result.returncode == 2
    assert result.stdout == ""
    assert "stage-bootstrap.md" in result.stderr
