"""Контейнер процесса собирается из провайдеров всех модулей (ADR-0020 §7)."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from app.entrypoints import cli
from app.entrypoints._wiring import MODULE_PROVIDERS

pytestmark = pytest.mark.unit

EXPECTED_MODULES = {
    "identity",
    "geo",
    "catalog",
    "media",
    "billing",
    "specialists",
    "pricing",
    "deals",
    "jobs",
    "messaging",
    "reviews",
    "search",
    "growth",
    "notifications",
    "moderation",
}


MODULES_DIR = Path(__file__).resolve().parents[2] / "src" / "app" / "modules"


def test_every_domain_module_has_a_provider() -> None:
    """Каждый пакет в modules/ подключён к контейнеру, и модули MVP на месте."""
    packages = {p.name for p in MODULES_DIR.iterdir() if p.is_dir() and not p.name.startswith("_")}
    modules = {provider.__module__.split(".")[2] for provider in MODULE_PROVIDERS}
    assert modules == packages
    assert modules >= EXPECTED_MODULES


def test_cli_version() -> None:
    result = CliRunner().invoke(cli.app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"
