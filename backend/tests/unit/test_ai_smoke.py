"""`cli ai-smoke` (DEVELOPMENT_PLAN 2.4) без сети: транспорты отвечают записанными ответами.

Живой вызов с ключами — вручную: `make cli ARGS=ai-smoke`.
"""

import json
from pathlib import Path
from typing import Any

import httpx
import httpx2
import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from app.entrypoints import cli
from app.entrypoints._ai_smoke import run_ai_smoke
from app.platform.settings import AiSettings

pytestmark = pytest.mark.unit

RECORDED = Path(__file__).resolve().parent / "platform" / "recorded"


def recorded(name: str) -> Any:
    return json.loads((RECORDED / name).read_text(encoding="utf-8"))


def verdict(label: str) -> dict[str, Any]:
    text = json.dumps({"label": label, "confidence": 0.9, "explanation": "Пример."})
    return {**recorded("anthropic_prepayment.json"), "content": [{"type": "text", "text": text}]}


def openai_transport(status: int = 200) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        text = json.loads(request.content)["input"]
        name = (
            "openai_moderation_flagged.json"
            if "Ubiću" in text
            else "openai_moderation_clean_image.json"
        )
        return httpx.Response(status, json=recorded(name))

    return httpx.MockTransport(handle)


def anthropic_transport() -> httpx2.MockTransport:
    def handle(request: httpx2.Request) -> httpx2.Response:
        content = json.loads(request.content)["messages"][0]["content"]
        if "unapred" in content:
            return httpx2.Response(200, json=recorded("anthropic_prepayment.json"))
        return httpx2.Response(200, json=verdict("vacancy" if "Zapošljavamo" in content else "ok"))

    return httpx2.MockTransport(handle)


def settings(*, openai: bool = True, anthropic: bool = True) -> AiSettings:
    return AiSettings(
        _env_file=None,  # type: ignore[call-arg]  # параметр pydantic-settings
        openai_api_key=SecretStr("sk-test") if openai else None,
        anthropic_api_key=SecretStr("sk-ant-test") if anthropic else None,
    )


async def test_smoke_reports_every_check_and_records_raw_answers(tmp_path: Path) -> None:
    report = await run_ai_smoke(
        settings(),
        tmp_path,
        openai_transport=openai_transport(),
        anthropic_transport=anthropic_transport(),
    )

    [flagged] = recorded("openai_moderation_flagged.json")["results"]
    top = max(flagged["category_scores"].items(), key=lambda item: item[1])
    [block] = recorded("anthropic_prepayment.json")["content"]
    scam = json.loads(block["text"])
    assert not report.failed
    assert report.lines[0].startswith("moderation clean: flagged=False")
    assert report.lines[1].startswith(f"moderation threat: flagged=True [{top[0]} {top[1]:.2f}")
    assert [line.split(":")[0] for line in report.lines[2:]] == [
        "classifier job",
        "classifier response",
        "classifier job",
    ]
    assert f"{scam['label']} {scam['confidence']:.2f}" in report.lines[3]
    assert "ожидалось" not in "".join(report.lines)
    assert sorted(path.name for path in report.recorded) == [
        "anthropic_prepayment.json",
        "openai_moderation_flagged.json",
    ]
    for path in report.recorded:
        assert json.loads(path.read_text(encoding="utf-8")) == recorded(path.name)


async def test_smoke_fails_when_a_provider_is_unavailable() -> None:
    report = await run_ai_smoke(
        settings(anthropic=False), openai_transport=openai_transport(status=401)
    )

    assert report.failed
    assert report.lines == [
        "moderation clean: НЕДОСТУПНО (provider_error)",
        "moderation threat: НЕДОСТУПНО (provider_error)",
        "classifier: пропущено — нет AI_ANTHROPIC_API_KEY (K26)",
    ]
    assert report.recorded == []


async def test_smoke_records_only_answers_the_tests_expect(tmp_path: Path) -> None:
    def surprising(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=verdict("off_platform_payment"))

    report = await run_ai_smoke(
        settings(openai=False), tmp_path, anthropic_transport=httpx2.MockTransport(surprising)
    )

    assert "ожидалось prepayment_scam" in report.lines[2]
    assert report.recorded == []  # запись с другой меткой сломала бы контрактные тесты


def test_command_without_keys_exits_with_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # ключи из backend/.env разработчика тесту не нужны: живого вызова быть не должно
    monkeypatch.setattr(cli, "AiSettings", lambda: settings(openai=False, anthropic=False))

    result = CliRunner().invoke(cli.app, ["ai-smoke"])

    assert result.exit_code == 1
    assert "нечего проверять" in result.output
