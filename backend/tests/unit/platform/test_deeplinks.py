"""Кодек deep links (ARCHITECTURE §11.4): golden-векторы — общие с packages/links."""

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import yaml

from app.platform.telegram.deeplinks import (
    BASE62_ALPHABET,
    START_PARAM_MAX_LENGTH,
    LinkDocument,
    LinkSection,
    LinkType,
    ReservedCode,
    StartLink,
    base62_to_uuid,
    encode_start_param,
    is_valid_start_param,
    parse_start_param,
    uuid_to_base62,
)
from app.platform.telegram.errors import InvalidStartLinkError

pytestmark = pytest.mark.unit

GOLDEN_PATH = Path(__file__).resolve().parents[4] / "packages" / "links" / "golden.json"
GOLDEN: dict[str, Any] = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
CI_BACKEND_PATH = GOLDEN_PATH.parents[2] / ".github" / "workflows" / "ci-backend.yml"
ID = UUID("0192f5a8-7c3e-7b21-9d4f-3a6b8c1e2f47")


def from_golden(data: dict[str, str]) -> StartLink:
    return StartLink(
        type=LinkType(data["type"]),
        id=UUID(data["id"]) if "id" in data else None,
        code=ReservedCode(data["code"]) if "code" in data else None,
        value=data.get("value"),
        document=LinkDocument(data["document"]) if "document" in data else None,
        section=LinkSection(data["section"]) if "section" in data else None,
        ref=data.get("ref"),
    )


def as_golden(link: StartLink) -> dict[str, str]:
    """Форма ссылки в golden.json: как объект StartLink в TypeScript, без пустых полей."""
    fields = {
        "type": link.type.value,
        "id": str(link.id) if link.id else None,
        "code": link.code.value if link.code else None,
        "value": link.value,
        "document": link.document.value if link.document else None,
        "section": link.section.value if link.section else None,
        "ref": link.ref,
    }
    return {key: value for key, value in fields.items() if value is not None}


# --- golden-векторы -----------------------------------------------------------------------


def test_alphabet_matches_frontend() -> None:
    assert GOLDEN["alphabet"] == BASE62_ALPHABET


@pytest.mark.parametrize("vector", GOLDEN["uuid"], ids=lambda v: v["uuid"])
def test_uuid_base62_vectors(vector: dict[str, str]) -> None:
    assert uuid_to_base62(UUID(vector["uuid"])) == vector["base62"]
    assert base62_to_uuid(vector["base62"]) == UUID(vector["uuid"])


@pytest.mark.parametrize("vector", GOLDEN["valid"], ids=lambda v: v["param"])
def test_valid_vectors_encode_and_parse(vector: dict[str, Any]) -> None:
    assert encode_start_param(from_golden(vector["link"])) == vector["param"]
    parsed = parse_start_param(vector["param"])
    assert parsed is not None
    assert as_golden(parsed) == vector["link"]


@pytest.mark.parametrize("param", GOLDEN["invalid"])
def test_invalid_vectors_are_not_parsed(param: str) -> None:
    assert parse_start_param(param) is None


def test_ci_backend_runs_on_golden_changes() -> None:
    """Правка golden.json или TS-кодека без backend/ всё равно запускает эти тесты в CI.

    main проверяется ночным прогоном без фильтра путей, поэтому фильтр нужен только у PR.
    """
    workflow = yaml.safe_load(CI_BACKEND_PATH.read_text(encoding="utf-8"))
    triggers = workflow[True]  # PyYAML (YAML 1.1) читает ключ `on` как True
    assert "packages/links/**" in triggers["pull_request"]["paths"]
    assert "schedule" in triggers


# --- base62 -------------------------------------------------------------------------------


def test_base62_is_always_22_chars() -> None:
    for vector in GOLDEN["uuid"]:
        assert len(uuid_to_base62(UUID(vector["uuid"]))) == 22


@pytest.mark.parametrize("value", ["7n42DGM5Tflk9n8mt7Fhc8", "short", "1Xh3kQ9vB7mZ2pR4sT8dL!", ""])
def test_base62_rejects_non_uuid_and_overflow(value: str) -> None:
    assert base62_to_uuid(value) is None


def test_base62_rejects_trailing_newline() -> None:
    """`$` в регулярке Python пропускает \\n в конце — проверка строгая, как в TypeScript."""
    assert base62_to_uuid(uuid_to_base62(ID) + "\n") is None
    assert parse_start_param("h\n") is None


# --- коды startapp ------------------------------------------------------------------------


def test_limit_is_64_chars() -> None:
    max_ref = "A" * (START_PARAM_MAX_LENGTH - 26)
    code = encode_start_param(StartLink(type=LinkType.SPECIALIST, id=ID, ref=max_ref))
    assert len(code) == START_PARAM_MAX_LENGTH
    with pytest.raises(InvalidStartLinkError):
        encode_start_param(StartLink(type=LinkType.SPECIALIST, id=ID, ref=f"{max_ref}A"))
    assert not is_valid_start_param("h" * 65)
    assert parse_start_param("h" * 65) is None


def test_gh_and_h_are_different_types() -> None:
    assert parse_start_param("h") == StartLink(type=LinkType.HOME)
    assert parse_start_param("gh") == StartLink(
        type=LinkType.RESERVED, code=ReservedCode.GOODS_HOME
    )
    assert encode_start_param(StartLink(type=LinkType.HOME)) == "h"
    assert (
        encode_start_param(StartLink(type=LinkType.RESERVED, code=ReservedCode.GOODS_HOME)) == "gh"
    )


def test_ref_is_only_a_suffix() -> None:
    assert parse_start_param("h_rAB12CD") == StartLink(type=LinkType.HOME, ref="AB12CD")
    assert parse_start_param("rAB12CD") is None
    # у зарезервированного кода значение может начинаться с r: это значение, а не реферал
    assert parse_start_param("gs_r42") == StartLink(
        type=LinkType.RESERVED, code=ReservedCode.GOODS_SAVED_SEARCH, value="r42"
    )


def test_telegram_partner_params_are_not_ours() -> None:
    assert not is_valid_start_param("_tgr_abc")
    assert parse_start_param("_tgr_abc") is None


@pytest.mark.parametrize(
    "fields",
    [
        {"type": LinkType.HOME, "ref": "A_B"},
        {"type": LinkType.RESERVED, "code": ReservedCode.GOODS_SAVED_SEARCH},
        {"type": LinkType.RESERVED, "code": ReservedCode.GOODS_HOME, "value": "1"},
        {"type": LinkType.RESERVED, "code": ReservedCode.GOODS_PARTNER_CHAT, "value": "a_b"},
        {"type": LinkType.RESERVED, "code": ReservedCode.GOODS_SAVED_SEARCH, "value": ""},
        {"type": LinkType.JOB},
        {"type": LinkType.HOME, "id": ID},
        {"type": LinkType.NEW_JOB, "id": ID},
        {"type": LinkType.MINE},
        {"type": LinkType.HOME, "section": LinkSection.JOBS},
        {"type": LinkType.LEGAL, "document": LinkDocument.TERMS, "section": LinkSection.JOBS},
    ],
    ids=[
        "ref-underscore",
        "gs-no-value",
        "gh-value",
        "gc-underscore",
        "gs-empty",
        "job-no-id",
        "h-id",
        "n-id",
        "m-no-section",
        "h-section",
        "l-section",
    ],
)
def test_invalid_links_are_rejected(fields: dict[str, Any]) -> None:
    with pytest.raises(InvalidStartLinkError):
        StartLink(**fields)


@pytest.mark.parametrize("value", [None, ""])
def test_empty_param_is_not_a_link(value: str | None) -> None:
    assert parse_start_param(value) is None
