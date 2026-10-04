"""Проверка сидов пилотной зоны (DEVELOPMENT_PLAN 0.27): `cli seeds-validate`.

- `seeds/catalog/taxonomy.yaml` — схема, уникальные slug, глубина ≤ 3, CHECK локалей
  (ru и sr-Cyrl), ориентиры цен по известным городам;
- `seeds/catalog/queries.yaml` — каждая строка ведёт в существующую категорию, у каждой
  категории второго уровня есть запросы;
- `seeds/geo/<город>.geojson` — валидные MultiPolygon в границах Сербии, уникальные slug,
  родитель — municipality, центр внутри своего полигона, CHECK локалей.

- `seeds/moderation/content_rules.yaml` — каждое правило проходит ту же проверку, что правка в
  админке (`compile_rule`; регулярки — движком RE2: шаблон, который RE2 не собирает, — ошибка),
  нет повторов (в том числе по скелету: «кокаин» и «kokain» — одно слово); `rule_examples.yaml` —
  набор «текст → действие и категории» проходит на этом словаре вместе с детекторами
  platform/text.

Модели здесь — входной формат загрузки в БД (`cli seed`): `load_city_seeds` (1.3a),
`load_catalog_seed` (1.3b) и `load_content_rules_seed` (2.4) превращают файлы в DTO импорта
модулей geo, catalog и moderation.
"""

import json
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)
from shapely.geometry import MultiPolygon, Point, shape
from shapely.ops import unary_union

from app.modules.catalog.api import RiskLevel
from app.modules.catalog.application.dto import CategorySeed, TagSeed
from app.modules.catalog.domain.category import PriceHint as PriceHintValue
from app.modules.catalog.domain.category import PriceUnit
from app.modules.catalog.domain.terms import MAX_TERM_LENGTH, SearchTerm, TermLanguage
from app.modules.geo.application.dto import CitySeed, DistrictSeed
from app.modules.geo.domain.place import DistrictKind as GeoDistrictKind
from app.modules.moderation.domain.rules import (
    ContentRule,
    InvalidRuleError,
    RuleAction,
    RuleCategory,
    RuleKind,
    RuleLanguage,
    RuleSet,
    compile_rule,
)
from app.modules.moderation.infrastructure.rule_examples import ExamplesFile
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.localized import Locale, LocalizedText
from app.platform.text.normalize import skeleton

SEEDS_DIR = Path(__file__).resolve().parents[3] / "seeds"
SERBIA_BOUNDS = (18.8, 42.2, 23.1, 46.2)
"""lon_min, lat_min, lon_max, lat_max: грубая рамка Сербии против перепутанных координат."""
MAX_DEPTH = 3
MIN_SIBLING_OVERLAP = 0.05
"""Доля площади меньшего района, при которой пересечение соседей — ошибка данных."""

Slug = Annotated[str, Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=64)]
Term = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TERM_LENGTH)
]
"""Строка словаря поиска (search_terms.term): синоним или название на любой локали."""


class Names(BaseModel):
    """Названия: ru и sr-Cyrl обязательны (CHECK в БД), sr-Latn — транслит, если не задан.

    Названия категорий и тегов попадают в словарь поиска — отсюда предел длины Term.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ru: Term
    sr_cyrl: Term = Field(alias="sr-Cyrl")
    sr_latn: Term | None = Field(default=None, alias="sr-Latn")
    en: Term | None = None


class PriceHint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rsd: tuple[int, int]
    unit: PriceUnit

    @field_validator("rsd")
    @classmethod
    def _range(cls, value: tuple[int, int]) -> tuple[int, int]:
        low, high = value
        if not 0 < low <= high:
            raise ValueError("rsd must be [from, to] with 0 < from <= to")
        return value


class Terms(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ru: list[Term] = Field(default_factory=list)
    sr: list[Term] = Field(default_factory=list)
    en: list[Term] = Field(default_factory=list)


class Tag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: Slug
    name: Names


class Category(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: Slug
    name: Names
    icon: str | None = Field(default=None, max_length=32)
    """Имя иконки дизайн-системы: categories.icon — varchar(32)."""
    risk_level: int = Field(default=0, ge=0, le=2)
    price_hint: dict[str, PriceHint] = Field(default_factory=dict)
    terms: Terms = Field(default_factory=Terms)
    tags: list[Tag] = Field(default_factory=list)
    children: list[Category] = Field(default_factory=list)


class Taxonomy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    categories: list[Category] = Field(min_length=1)


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: str = Field(min_length=2)
    category: Slug


class Queries(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queries: list[Query] = Field(min_length=1)


class DistrictKind(StrEnum):
    MUNICIPALITY = "municipality"
    NEIGHBORHOOD = "neighborhood"


class District(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: Slug
    kind: DistrictKind
    parent: Slug | None = None
    name: Names
    aliases: list[str] = Field(default_factory=list)
    center: tuple[float, float]
    source: str = Field(min_length=1)


class CityInfo(BaseModel):
    slug: Slug
    name: Names | None = None


class CityEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: Slug
    name: Names
    center: tuple[float, float]
    active: bool = False
    sort_order: int = 0


class Cities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cities: list[CityEntry] = Field(min_length=1)


class GeoCollection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    city: CityInfo
    attribution: str = Field(min_length=10)
    features: list[dict[str, Any]] = Field(min_length=1)

    @model_validator(mode="after")
    def _collection(self) -> GeoCollection:
        if self.type != "FeatureCollection":
            raise ValueError("type must be FeatureCollection")
        return self


class RuleGroup(BaseModel):
    """Правила одной категории и действия: ровно один из списков words, regex, domains."""

    model_config = ConfigDict(extra="forbid")

    category: RuleCategory
    action: RuleAction
    lang: RuleLanguage | None = None
    active: bool = True
    words: list[str] = Field(default_factory=list)
    regex: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_kind(self) -> RuleGroup:
        if sum(1 for patterns in (self.words, self.regex, self.domains) if patterns) != 1:
            raise ValueError("a group needs exactly one non-empty list: words, regex or domains")
        return self

    def rules(self) -> list[ContentRule]:
        kind, patterns = next(
            (kind, patterns)
            for kind, patterns in (
                (RuleKind.WORD, self.words),
                (RuleKind.REGEX, self.regex),
                (RuleKind.DOMAIN, self.domains),
            )
            if patterns
        )
        return [
            ContentRule(
                pattern=pattern,
                kind=kind,
                action=self.action,
                category=self.category,
                lang=self.lang,
                active=self.active,
            )
            for pattern in patterns
        ]


class ContentRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    rules: list[RuleGroup] = Field(min_length=1)


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    summary: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _walk(categories: list[Category], depth: int = 1) -> Iterator[tuple[Category, int]]:
    for category in categories:
        yield category, depth
        yield from _walk(category.children, depth + 1)


def _load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as file:
        return yaml.safe_load(file)


def _pydantic_errors(path: Path, exc: ValidationError) -> list[str]:
    return [f"{path.name}: {'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]


def check_geo(path: Path, report: Report) -> str | None:
    """Проверить GeoJSON города; вернуть slug города или None при ошибке формата."""
    try:
        collection = GeoCollection.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (ValidationError, json.JSONDecodeError) as exc:
        if isinstance(exc, ValidationError):
            report.errors.extend(_pydantic_errors(path, exc))
        else:
            report.errors.append(f"{path.name}: {exc}")
        return None
    districts: dict[str, tuple[District, MultiPolygon]] = {}
    lon_min, lat_min, lon_max, lat_max = SERBIA_BOUNDS
    for index, feature in enumerate(collection.features):
        try:
            district = District.model_validate(feature.get("properties"))
        except ValidationError as exc:
            report.errors.extend(f"feature {index}: {msg}" for msg in _pydantic_errors(path, exc))
            continue
        geometry = shape(feature.get("geometry") or {})
        name = f"{path.name}: {district.slug}"
        if district.slug in districts:
            report.errors.append(f"{name}: duplicate slug")
        if not isinstance(geometry, MultiPolygon) or geometry.is_empty:
            report.errors.append(f"{name}: geometry must be a non-empty MultiPolygon")
            continue
        if not geometry.is_valid:
            report.errors.append(f"{name}: invalid polygon")
        x1, y1, x2, y2 = geometry.bounds
        if x1 < lon_min or x2 > lon_max or y1 < lat_min or y2 > lat_max:
            report.errors.append(f"{name}: outside Serbia (lon/lat swapped?)")
        if not geometry.covers(Point(district.center)):
            report.errors.append(f"{name}: center is outside the polygon")
        districts[district.slug] = (district, geometry)
    for slug, (district, _) in districts.items():
        if district.parent is None:
            continue
        parent = districts.get(district.parent)
        if parent is None or parent[0].kind is not DistrictKind.MUNICIPALITY:
            report.errors.append(f"{path.name}: {slug}: parent must be a municipality in the file")
        elif not parent[1].covers(Point(district.center)):
            report.warnings.append(
                f"{path.name}: {slug}: center is outside parent {district.parent}"
            )
    siblings = [(s, g) for s, (d, g) in districts.items() if d.kind is DistrictKind.NEIGHBORHOOD]
    for i, (slug_a, geom_a) in enumerate(siblings):
        for slug_b, geom_b in siblings[i + 1 :]:
            overlap = geom_a.intersection(geom_b).area
            if overlap > MIN_SIBLING_OVERLAP * min(geom_a.area, geom_b.area):
                report.errors.append(f"{path.name}: {slug_a} and {slug_b} overlap")
    kinds = Counter(d.kind.value for d, _ in districts.values())
    report.summary.append(
        f"{path.name}: {len(districts)} districts ({dict(sorted(kinds.items()))})"
    )
    return collection.city.slug


def check_taxonomy(path: Path, cities: set[str], report: Report) -> set[str]:
    """Проверить таксономию; вернуть slug категорий второго уровня."""
    try:
        taxonomy = Taxonomy.model_validate(_load_yaml(path))
    except ValidationError as exc:
        report.errors.extend(_pydantic_errors(path, exc))
        return set()
    slugs: Counter[str] = Counter()
    leaves: set[str] = set()
    terms = 0
    for category, depth in _walk(taxonomy.categories):
        slugs[category.slug] += 1
        slugs.update(tag.slug for tag in category.tags)
        terms += len(category.terms.ru) + len(category.terms.sr) + len(category.terms.en)
        if depth > MAX_DEPTH:
            report.errors.append(f"{path.name}: {category.slug}: deeper than {MAX_DEPTH}")
        if depth == 2:
            leaves.add(category.slug)
            if not category.price_hint:
                report.warnings.append(f"{path.name}: {category.slug}: no price_hint")
        unknown = set(category.price_hint) - cities
        if unknown:
            report.errors.append(f"{path.name}: {category.slug}: unknown cities {sorted(unknown)}")
    duplicates = sorted(slug for slug, count in slugs.items() if count > 1)
    if duplicates:
        report.errors.append(f"{path.name}: duplicate slugs {duplicates}")
    report.summary.append(
        f"{path.name}: {len(taxonomy.categories)} categories, {len(leaves)} subcategories, "
        f"{terms} search terms"
    )
    return leaves


def check_queries(path: Path, leaves: set[str], report: Report) -> None:
    try:
        queries = Queries.model_validate(_load_yaml(path))
    except ValidationError as exc:
        report.errors.extend(_pydantic_errors(path, exc))
        return
    texts = Counter(q.q.casefold() for q in queries.queries)
    repeated = sorted(text for text, count in texts.items() if count > 1)
    if repeated:
        report.errors.append(f"{path.name}: duplicate queries {repeated}")
    unknown = sorted({q.category for q in queries.queries} - leaves)
    if unknown:
        report.errors.append(f"{path.name}: unknown categories {unknown}")
    uncovered = sorted(leaves - {q.category for q in queries.queries})
    if uncovered:
        report.errors.append(f"{path.name}: no queries for {uncovered}")
    report.summary.append(f"{path.name}: {len(queries.queries)} queries")


def check_cities(path: Path, report: Report) -> set[str]:
    try:
        cities = Cities.model_validate(_load_yaml(path))
    except ValidationError as exc:
        report.errors.extend(_pydantic_errors(path, exc))
        return set()
    slugs = [city.slug for city in cities.cities]
    if len(set(slugs)) != len(slugs):
        report.errors.append(f"{path.name}: duplicate city slugs")
    report.summary.append(f"{path.name}: {len(slugs)} cities")
    return set(slugs)


def validate(seeds: Path = SEEDS_DIR) -> Report:
    report = Report()
    known = check_cities(seeds / "geo" / "cities.yaml", report)
    cities = {
        city
        for path in sorted((seeds / "geo").glob("*.geojson"))
        if (city := check_geo(path, report))
    }
    if not cities:
        report.errors.append("geo: no district files")
    if unknown := sorted(cities - known):
        report.errors.append(f"geo: cities {unknown} are not in cities.yaml")
    leaves = check_taxonomy(seeds / "catalog" / "taxonomy.yaml", cities, report)
    check_queries(seeds / "catalog" / "queries.yaml", leaves, report)
    rules = check_content_rules(seeds / "moderation" / "content_rules.yaml", report)
    check_rule_examples(seeds / "moderation" / "rule_examples.yaml", rules, report)
    return report


def check_content_rules(path: Path, report: Report) -> list[ContentRule]:
    try:
        seed = ContentRules.model_validate(_load_yaml(path))
    except ValidationError as exc:
        report.errors.extend(_pydantic_errors(path, exc))
        return []
    rules = [rule for group in seed.rules for rule in group.rules()]
    seen: dict[tuple[RuleKind, str], int] = {}
    for index, rule in enumerate(rules):
        try:
            compile_rule(rule)
        except InvalidRuleError as exc:
            report.errors.append(f"{path.name}: {rule.kind.value} {rule.pattern!r}: {exc}")
            continue
        same = rule.pattern if rule.kind is not RuleKind.WORD else skeleton(rule.pattern)
        if rule.kind is RuleKind.WORD:
            _check_word_length(path, rule.pattern, same, report)
        key = (rule.kind, same + ("*" if rule.pattern.endswith("*") else ""))
        if (first := seen.setdefault(key, index)) != index:
            report.errors.append(
                f"{path.name}: {rule.kind.value} {rule.pattern!r} repeats {rules[first].pattern!r}"
            )
    kinds = Counter(rule.kind.value for rule in rules)
    report.summary.append(
        f"{path.name}: {len(rules)} rules ("
        + ", ".join(f"{kind} {count}" for kind, count in sorted(kinds.items()))
        + ")"
    )
    return rules


MIN_WORD = 3
"""Слово словаря короче в скелете — ловит всё подряд («cvv» → «cv»)."""
SHORT_WORD = 5


def _check_word_length(path: Path, pattern: str, words: str, report: Report) -> None:
    letters = len(words.replace(" ", ""))
    if letters < MIN_WORD:
        report.errors.append(
            f"{path.name}: word {pattern!r} is {words!r} in the skeleton — too short"
        )
    elif letters < SHORT_WORD and not pattern.endswith("*") and " " not in words:
        report.warnings.append(
            f"{path.name}: word {pattern!r} is only {words!r} in the skeleton — check that"
            " ordinary words do not match"
        )


def check_rule_examples(path: Path, rules: list[ContentRule], report: Report) -> None:
    try:
        examples = ExamplesFile.model_validate(_load_yaml(path))
    except ValidationError as exc:
        report.errors.extend(_pydantic_errors(path, exc))
        return
    ruleset = RuleSet(rules)
    for example in examples.examples:
        verdict = ruleset.check(example.text)
        action = verdict.action.value if verdict.action is not None else "pass"
        categories = sorted(c.value for c in verdict.categories)
        expected = sorted(c.value for c in example.categories)
        if (action, categories) != (example.action, expected):
            report.errors.append(
                f"{path.name}: {example.text!r}: expected {example.action} {expected},"
                f" got {action} {categories}"
            )
    report.summary.append(f"{path.name}: {len(examples.examples)} examples")


def load_city_seeds(seeds: Path = SEEDS_DIR) -> list[CitySeed]:
    """Сиды городов для импорта (1.3a): cities.yaml + районы из <город>.geojson."""
    cities = Cities.model_validate(_load_yaml(seeds / "geo" / "cities.yaml"))
    result = []
    for city in cities.cities:
        path = seeds / "geo" / f"{city.slug}.geojson"
        districts: list[DistrictSeed] = []
        polygons: list[MultiPolygon] = []
        if path.exists():
            collection = GeoCollection.model_validate(json.loads(path.read_text(encoding="utf-8")))
            for feature in collection.features:
                district = District.model_validate(feature["properties"])
                geometry = shape(feature["geometry"])
                if not isinstance(geometry, MultiPolygon):
                    raise TypeError(f"{path.name}: {district.slug}: expected MultiPolygon")
                polygons.append(geometry)
                districts.append(
                    DistrictSeed(
                        slug=district.slug,
                        kind=GeoDistrictKind(district.kind.value),
                        parent=district.parent,
                        name=_localized(district.name),
                        aliases=tuple(district.aliases),
                        center=GeoPoint(lat=district.center[1], lon=district.center[0]),
                        boundary_wkt=geometry.wkt,
                        source=district.source,
                    )
                )
        boundary: MultiPolygon | None = None
        if polygons:
            union = unary_union(polygons)
            boundary = union if isinstance(union, MultiPolygon) else MultiPolygon([union])  # type: ignore[list-item]  # union полигонов — Polygon
        result.append(
            CitySeed(
                slug=city.slug,
                name=_localized(city.name),
                center=GeoPoint(lat=city.center[1], lon=city.center[0]),
                active=city.active,
                sort_order=city.sort_order,
                boundary_wkt=boundary.wkt if boundary is not None else None,
                districts=tuple(districts),
            )
        )
    return result


def load_catalog_seed(seeds: Path = SEEDS_DIR) -> list[CategorySeed]:
    """Таксономия для импорта (1.3b): порядок в YAML — порядок показа, цены — в пара."""
    taxonomy = Taxonomy.model_validate(_load_yaml(seeds / "catalog" / "taxonomy.yaml"))
    return [_category(category, index) for index, category in enumerate(taxonomy.categories)]


def load_content_rules_seed(seeds: Path = SEEDS_DIR) -> list[ContentRule]:
    """Словарь контент-правил для импорта (2.4): все правила файла, выключенные тоже."""
    seed = ContentRules.model_validate(_load_yaml(seeds / "moderation" / "content_rules.yaml"))
    return [rule for group in seed.rules for rule in group.rules()]


def _category(category: Category, sort_order: int) -> CategorySeed:
    terms = category.terms
    synonyms = [
        SearchTerm.synonym(text, language)
        for language, texts in (
            (TermLanguage.RU, terms.ru),
            (TermLanguage.SR, terms.sr),
            (TermLanguage.EN, terms.en),
        )
        for text in texts
    ]
    return CategorySeed(
        slug=category.slug,
        name=_localized(category.name),
        icon=category.icon,
        risk_level=RiskLevel(category.risk_level),
        sort_order=sort_order,
        price_hints={
            city: PriceHintValue.from_rsd(*hint.rsd, hint.unit)
            for city, hint in category.price_hint.items()
        },
        synonyms=tuple(synonyms),
        tags=tuple(TagSeed(slug=tag.slug, name=_localized(tag.name)) for tag in category.tags),
        children=tuple(_category(child, index) for index, child in enumerate(category.children)),
    )


def _localized(names: Names) -> LocalizedText:
    values = {Locale.RU: names.ru, Locale.SR_CYRL: names.sr_cyrl}
    if names.sr_latn:
        values[Locale.SR_LATN] = names.sr_latn
    if names.en:
        values[Locale.EN] = names.en
    return LocalizedText(values)
