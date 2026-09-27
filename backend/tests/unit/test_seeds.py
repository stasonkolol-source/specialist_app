"""`cli seeds-validate` (DEVELOPMENT_PLAN 0.27): сиды репозитория проходят, испорченные — нет."""

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from app.entrypoints import cli
from app.entrypoints.seeds import SEEDS_DIR, validate

pytestmark = pytest.mark.unit


def test_repository_seeds_are_valid() -> None:
    report = validate()
    assert report.errors == []
    assert any("districts" in line for line in report.summary)
    result = CliRunner().invoke(cli.app, ["seeds-validate"])
    assert result.exit_code == 0, result.output
    assert "seeds: OK" in result.output


@pytest.fixture
def seeds(tmp_path: Path) -> Path:
    shutil.copytree(SEEDS_DIR, tmp_path / "seeds", ignore=shutil.ignore_patterns("tools"))
    return tmp_path / "seeds"


def _edit_yaml(path: Path, change: Callable[[Any], None]) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _edit_geo(path: Path, change: Callable[[dict[str, Any]], None]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _taxonomy(seeds: Path) -> Path:
    return seeds / "catalog" / "taxonomy.yaml"


def _geo(seeds: Path) -> Path:
    return seeds / "geo" / "novi-sad.geojson"


def _first_leaf(data: Any) -> dict[str, Any]:
    leaf: dict[str, Any] = data["categories"][0]["children"][0]
    return leaf


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["categories"][0]["name"].pop("sr-Cyrl"), "sr-Cyrl"),
        (lambda d: d["categories"][1].update(slug=d["categories"][0]["slug"]), "duplicate slugs"),
        (
            lambda d: _first_leaf(d)["price_hint"].update(
                {"beograd": {"rsd": [1, 2], "unit": "hour"}}
            ),
            "unknown cities",
        ),
        (
            lambda d: _first_leaf(d)["price_hint"]["novi-sad"].update(rsd=[500, 100]),
            "0 < from <= to",
        ),
        (lambda d: _first_leaf(d)["price_hint"]["novi-sad"].update(unit="week"), "unit"),
        (lambda d: _first_leaf(d).update(slug="Bad Slug"), "slug"),
        (
            lambda d: _first_leaf(d).update(
                children=[
                    {
                        "slug": "c3",
                        "name": {"ru": "x", "sr-Cyrl": "x"},
                        "children": [{"slug": "c4", "name": {"ru": "x", "sr-Cyrl": "x"}}],
                    }
                ]
            ),
            "deeper than 3",
        ),
    ],
    ids=[
        "no-sr-cyrl",
        "duplicate-slug",
        "unknown-city",
        "bad-range",
        "bad-unit",
        "bad-slug",
        "too-deep",
    ],
)
def test_broken_taxonomy_is_reported(
    seeds: Path, change: Callable[[Any], None], message: str
) -> None:
    _edit_yaml(_taxonomy(seeds), change)
    report = validate(seeds)
    assert any(message in error for error in report.errors), report.errors


def test_queries_must_cover_every_subcategory(seeds: Path) -> None:
    def drop_plumbing(data: Any) -> None:
        data["queries"] = [q for q in data["queries"] if q["category"] != "plumbing"]
        data["queries"].append({"q": "что-то", "category": "no-such-category"})

    _edit_yaml(seeds / "catalog" / "queries.yaml", drop_plumbing)
    errors = validate(seeds).errors
    assert any("no queries for ['plumbing']" in e for e in errors)
    assert any("unknown categories ['no-such-category']" in e for e in errors)


def _swap(feature: dict[str, Any]) -> None:
    polygons = feature["geometry"]["coordinates"]
    feature["geometry"]["coordinates"] = [
        [[[y, x] for x, y in ring] for ring in polygon] for polygon in polygons
    ]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: _swap(d["features"][1]), "outside Serbia"),
        (lambda d: d["features"][1]["properties"].update(center=[19.0, 45.0]), "center is outside"),
        (lambda d: d["features"][2]["properties"].update(slug="liman-2"), "duplicate slug"),
        (
            lambda d: d["features"][2]["properties"].update(parent="liman-3"),
            "parent must be a municipality",
        ),
        (lambda d: d["features"][2].update(geometry=d["features"][3]["geometry"]), "overlap"),
        (lambda d: d["features"][2]["properties"]["name"].pop("ru"), "ru"),
        (lambda d: d.update(attribution=""), "attribution"),
    ],
    ids=["swapped", "center", "duplicate", "parent", "overlap", "no-ru", "attribution"],
)
def test_broken_geo_is_reported(
    seeds: Path, change: Callable[[dict[str, Any]], None], message: str
) -> None:
    _edit_geo(_geo(seeds), change)
    report = validate(seeds)
    assert any(message in error for error in report.errors), report.errors


def test_cli_fails_on_errors(seeds: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _edit_yaml(_taxonomy(seeds), lambda d: d["categories"][0]["name"].pop("ru"))
    monkeypatch.setattr("app.entrypoints.seeds.SEEDS_DIR", seeds)
    monkeypatch.setattr("app.entrypoints.seeds.validate.__defaults__", (seeds,))
    result = CliRunner().invoke(cli.app, ["seeds-validate"])
    assert result.exit_code == 1
