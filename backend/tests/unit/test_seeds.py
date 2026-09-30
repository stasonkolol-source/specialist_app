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
from app.entrypoints.seeds import SEEDS_DIR, load_catalog_seed, load_content_rules_seed, validate
from app.modules.catalog.api import RiskLevel
from app.modules.catalog.domain.category import PriceUnit
from app.modules.moderation.domain.rules import RuleAction, RuleKind
from app.platform.kernel.localized import Locale
from app.platform.kernel.money import Money

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
        # Пределы БД и словаря поиска: без них ошибку дал бы только `cli seed`.
        (
            lambda d: _first_leaf(d)["terms"]["ru"].insert(0, "x" * 121),
            "terms.ru.0: String should have at most 120 characters",
        ),
        (
            lambda d: _first_leaf(d)["terms"]["sr"].insert(0, "   "),
            "terms.sr.0: String should have at least 1 character",
        ),
        (
            lambda d: _first_leaf(d)["name"].update(ru="x" * 121),
            "name.ru: String should have at most 120 characters",
        ),
        (
            lambda d: _first_leaf(d)["tags"][0]["name"].update(en="x" * 121),
            "name.en: String should have at most 120 characters",
        ),
        (
            lambda d: _first_leaf(d).update(icon="i" * 40),
            "icon: String should have at most 32 characters",
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
        "long-synonym",
        "blank-synonym",
        "long-name",
        "long-tag-name",
        "long-icon",
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


def test_catalog_seed_for_import_keeps_order_para_and_scripts() -> None:
    categories = load_catalog_seed()
    assert [c.slug for c in categories] == ["handyman", "beauty", "cleaning", "moving", "lessons"]
    assert [c.sort_order for c in categories] == [0, 1, 2, 3, 4]
    handyman = categories[0]
    assert handyman.risk_level is RiskLevel.NORMAL
    assert handyman.price_hints == {}
    electrical = handyman.children[3]
    assert (electrical.slug, electrical.sort_order) == ("electrical", 3)
    hint = electrical.price_hints["novi-sad"]
    assert (hint.min, hint.max, hint.unit) == (Money(100_000), Money(400_000), PriceUnit.ITEM)
    assert Locale.SR_LATN not in electrical.name.values  # латиницу генерирует импорт
    locales = {term.text: term.locale for term in electrical.synonyms}
    assert locales["электрик"] is Locale.RU
    assert locales["električar"] is Locale.SR_LATN
    assert locales["струја"] is Locale.SR_CYRL
    assert locales["electrician"] is Locale.EN
    assert [tag.slug for tag in electrical.tags] == [
        "chandeliers",
        "sockets-and-switches",
        "fuse-box",
    ]


# --- словарь модерации (2.4) ---------------------------------------------------------------


def _rules(seeds: Path) -> Path:
    return seeds / "moderation" / "content_rules.yaml"


def _examples(seeds: Path) -> Path:
    return seeds / "moderation" / "rule_examples.yaml"


def _group(data: Any, category: str, action: str = "flag") -> dict[str, Any]:
    group: dict[str, Any] = next(
        g for g in data["rules"] if g["category"] == category and g["action"] == action
    )
    return group


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: _group(d, "spam")["words"].append("казино*"), "repeats 'казино*'"),
        (lambda d: _group(d, "drugs")["words"].append("KOKAIN*"), "repeats 'кокаин*'"),
        (lambda d: _group(d, "spam").update(regex=["(oops"]), "exactly one non-empty list"),
        (
            lambda d: d["rules"].append({"category": "spam", "action": "flag", "regex": ["(oops"]}),
            "does not compile",
        ),
        (
            lambda d: d["rules"].append({"category": "spam", "action": "flag", "words": ["pro*"]}),
            "at least 4",
        ),
        (
            lambda d: d["rules"].append({"category": "gambling", "action": "flag", "words": ["x"]}),
            "category",
        ),
    ],
    ids=["duplicate", "same-skeleton", "two-lists", "bad-regex", "short-stem", "bad-category"],
)
def test_broken_content_rules_are_reported(
    seeds: Path, change: Callable[[Any], None], message: str
) -> None:
    _edit_yaml(_rules(seeds), change)
    report = validate(seeds)
    assert any(message in error for error in report.errors), report.errors


def test_dictionary_change_that_breaks_an_example_is_reported(seeds: Path) -> None:
    _edit_yaml(_rules(seeds), lambda d: _group(d, "drugs", "block")["words"].remove("закладчик*"))
    _edit_yaml(_examples(seeds), lambda d: d["examples"].append({"text": "Ok", "action": "flag"}))

    errors = validate(seeds).errors

    assert any("'Ищем закладчиков, оплата каждый день': expected block" in e for e in errors)
    assert any("'Ok': expected flag [], got pass []" in e for e in errors)


def test_content_rules_seed_for_import_has_every_rule() -> None:
    rules = load_content_rules_seed()

    assert len({(rule.kind, rule.pattern) for rule in rules}) == len(rules)
    assert {rule.kind for rule in rules} == set(RuleKind)
    assert all(rule.active and rule.id is None for rule in rules)
    blocking = {rule.pattern for rule in rules if rule.action is RuleAction.BLOCK}
    assert blocking == {
        "закладчик*",
        "кладмен*",
        "курьер закладок",
        "делать закладки",
        "stash placer*",
        "drug courier*",
    }  # block — только однозначное: список меняет владелец, а не случайная правка
