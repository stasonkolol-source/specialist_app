"""`cli jwt-keys`: ключи в .env, без вывода значений, без перезаписи без --rotate."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.entrypoints import cli
from app.entrypoints._envfile import read_env
from app.platform.security.jwt import JwtKeys

pytestmark = pytest.mark.unit


def run(env: Path, *args: str) -> str:
    result = CliRunner().invoke(cli.app, ["jwt-keys", "--env-file", str(env), *args])
    assert result.exit_code == 0, result.output
    return result.output


def test_keys_are_created_once_and_rotated_on_request(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# comment\nAPP_ENV=dev\nJWT_KEYS=\n", encoding="utf-8")

    assert "added" in run(env)
    first = read_env(env)["JWT_KEYS"]
    assert "unchanged" in run(env)
    assert read_env(env)["JWT_KEYS"] == first

    output = run(env, "--rotate")
    rotated = read_env(env)["JWT_KEYS"]
    keys = JwtKeys.parse(rotated)
    assert rotated.endswith(first)
    assert keys.signing.kid != first.split(":")[0]
    assert len(keys.verifying) == 2
    run(env, "--rotate")
    assert len(JwtKeys.parse(read_env(env)["JWT_KEYS"]).verifying) == 2

    lines = env.read_text(encoding="utf-8").splitlines()
    assert lines[:2] == ["# comment", "APP_ENV=dev"]
    for value in rotated.split(","):
        assert value.split(":")[1] not in output


def test_broken_keys_are_not_rotated(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("JWT_KEYS=k1:broken\n", encoding="utf-8")
    result = CliRunner().invoke(cli.app, ["jwt-keys", "--env-file", str(env), "--rotate"])
    assert result.exit_code != 0
    assert read_env(env)["JWT_KEYS"] == "k1:broken"
