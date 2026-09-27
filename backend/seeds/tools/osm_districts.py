"""Полигоны районов пилотной зоны из OpenStreetMap → backend/seeds/geo/<город>.geojson.

    cd backend && uv run python seeds/tools/osm_districts.py novi-sad [raw-overpass.json]

Список районов и их «народные» названия — в DISTRICTS ниже: правит владелец (K21).
Геометрия упрощается до ~5 м, координаты — 6 знаков. Данные OSM — под ODbL, атрибуция
пишется в файл. Повторный запуск перезаписывает файл (данные OSM могли обновиться).
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, MultiPolygon, Polygon, mapping
from shapely.ops import polygonize, unary_union

from app.platform.kernel.translit import sr_cyrl_to_latn

OVERPASS = os.environ.get("OVERPASS_URL", "https://overpass-api.de/api/interpreter")  # noqa: TID251 — утилита вне приложения
USER_AGENT = "sosed-dev/0.1 (seed preparation; https://github.com/stasonkolol-source)"
SIMPLIFY_DEGREES = 0.00005
ATTRIBUTION = "© OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright)"


@dataclass(frozen=True)
class District:
    slug: str
    osm: str  # relation/<id> или way/<id>
    kind: str  # municipality | neighborhood
    parent: str | None = None
    ru: str | None = None  # русское название, если отличается от автоматического
    aliases: tuple[str, ...] = ()  # «народные» названия: ru и sr


NOVI_SAD: tuple[District, ...] = (
    District("novi-sad", "relation/9273976", "municipality", ru="Нови-Сад"),
    District(
        "stari-grad",
        "relation/11607351",
        "neighborhood",
        "novi-sad",
        ru="Старый город",
        aliases=("Центр", "Centar", "Центар"),
    ),
    District("liman-1", "relation/11607228", "neighborhood", "novi-sad"),
    District("liman-2", "relation/11607227", "neighborhood", "novi-sad"),
    District("liman-3", "relation/11607225", "neighborhood", "novi-sad"),
    District("liman-4", "relation/11607226", "neighborhood", "novi-sad"),
    District("grbavica", "relation/11607349", "neighborhood", "novi-sad"),
    District("adamovicevo-naselje", "relation/11607350", "neighborhood", "novi-sad"),
    District(
        "bistrica",
        "relation/11607343",
        "neighborhood",
        "novi-sad",
        aliases=("Новое поселение", "Novo naselje", "Ново насеље"),
    ),
    District("detelinara", "relation/11607345", "neighborhood", "novi-sad"),
    District("telep", "relation/11607340", "neighborhood", "novi-sad"),
    District("klisa", "relation/11607356", "neighborhood", "novi-sad"),
    District("podbara", "relation/11607352", "neighborhood", "novi-sad"),
    District("salajka", "relation/11607353", "neighborhood", "novi-sad"),
    District("rotkvarija", "relation/11607348", "neighborhood", "novi-sad"),
    District("satelit", "relation/11607342", "neighborhood", "novi-sad"),
    District("sajmiste", "relation/11607344", "neighborhood", "novi-sad"),
    District("sajlovo", "relation/13798643", "neighborhood", "novi-sad"),  # у quarter нет контура
    District("slana-bara", "relation/11607357", "neighborhood", "novi-sad"),
    District("adice", "relation/11607341", "neighborhood", "novi-sad"),
    District("banatic", "relation/11607347", "neighborhood", "novi-sad"),
    District("vidovdansko-naselje", "relation/11607358", "neighborhood", "novi-sad"),
    District("avijaticarsko-naselje", "relation/11607346", "neighborhood", "novi-sad"),
    District("jugovicevo", "relation/11607398", "neighborhood", "novi-sad"),
    District("petrovaradin", "relation/9274232", "neighborhood", ru="Петроварадин"),
    District("sremska-kamenica", "relation/9274163", "neighborhood", ru="Сремска-Каменица"),
    District("veternik", "relation/9274009", "neighborhood", ru="Ветерник"),
    District("futog", "relation/9273357", "neighborhood", ru="Футог"),
)

CITIES: dict[str, tuple[District, ...]] = {"novi-sad": NOVI_SAD}
CITY_NAMES = {
    "novi-sad": {"sr-Cyrl": "Нови Сад", "sr-Latn": "Novi Sad", "ru": "Нови-Сад", "en": "Novi Sad"}
}

_RU = str.maketrans({"ј": "й", "Ј": "Й", "ћ": "ч", "Ћ": "Ч"})
_RU_DIGRAPHS = {
    "љ": "ль",
    "Љ": "Ль",
    "њ": "нь",
    "Њ": "Нь",
    "ђ": "дж",
    "Ђ": "Дж",
    "џ": "дж",
    "Џ": "Дж",
}
_RU_SYLLABLES = (
    ("ија", "ия"),
    ("ја", "я"),
    ("Ја", "Я"),
    ("ју", "ю"),
    ("Ју", "Ю"),
    ("је", "е"),
    ("Је", "Е"),
)


def russian(serbian_cyrillic: str) -> str:
    """Черновое русское написание из сербской кириллицы (правит владелец, K21)."""
    text = serbian_cyrillic
    for source, target in _RU_SYLLABLES:
        text = text.replace(source, target)
    text = "".join(_RU_DIGRAPHS.get(ch, ch) for ch in text)
    return text.translate(_RU)


def _latin(tags: dict[str, str], key: str) -> str | None:
    value = tags.get(key)
    return value.removeprefix("MZ ") if value else None


def fetch(ids: list[str]) -> list[dict[str, Any]]:
    relations = ",".join(i.split("/")[1] for i in ids if i.startswith("relation/"))
    ways = ",".join(i.split("/")[1] for i in ids if i.startswith("way/"))
    parts = []
    if relations:
        parts.append(f"relation(id:{relations});")
    if ways:
        parts.append(f"way(id:{ways});")
    query = f"[out:json][timeout:120];({''.join(parts)});out geom;"
    data = urllib.parse.urlencode({"data": query}).encode()
    request = urllib.request.Request(  # noqa: S310 — адрес Overpass, https
        OVERPASS, data=data, headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=180) as response:  # noqa: S310
        payload: dict[str, Any] = json.load(response)
    elements: list[dict[str, Any]] = payload["elements"]
    return elements


def geometry(element: dict[str, Any]) -> MultiPolygon:
    if element["type"] == "way":
        ring = [(p["lon"], p["lat"]) for p in element["geometry"]]
        polygons = [Polygon(ring)]
    else:
        lines = [
            LineString([(p["lon"], p["lat"]) for p in member["geometry"]])
            for member in element["members"]
            if member["type"] == "way" and member.get("geometry")
        ]
        faces = list(polygonize(unary_union(lines)))
        outer = [f for f in faces if not any(f.within(g) and f is not g for g in faces)]
        polygons = outer or faces
    merged = unary_union(polygons).simplify(SIMPLIFY_DEGREES, preserve_topology=True)
    shape = merged if isinstance(merged, MultiPolygon) else MultiPolygon([merged])
    return _round(shape)


def _round(shape: MultiPolygon) -> MultiPolygon:
    def ring(coords: Any) -> list[tuple[float, float]]:
        return [(round(x, 6), round(y, 6)) for x, y in coords]

    return MultiPolygon(
        [
            Polygon(ring(p.exterior.coords), [ring(i.coords) for i in p.interiors])
            for p in shape.geoms
        ]
    )


def build(city: str, raw: Path | None = None) -> dict[str, Any]:
    """raw — сохранённый ответ Overpass: читается, если есть, иначе туда пишется новый."""
    districts = CITIES[city]
    if raw is not None and raw.exists():
        elements = json.loads(raw.read_text(encoding="utf-8"))
    else:
        elements = fetch([d.osm for d in districts])
        if raw is not None:
            raw.write_text(json.dumps(elements), encoding="utf-8")
    by_osm = {f"{e['type']}/{e['id']}": e for e in elements}
    features = []
    for district in districts:
        element = by_osm[district.osm]
        tags = element["tags"]
        shape = geometry(element)
        sr_cyrl = tags["name"].removeprefix("МЗ ")
        sr_latn = _latin(tags, "name:sr-Latn") or sr_cyrl_to_latn(sr_cyrl)
        center = shape.representative_point()
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "slug": district.slug,
                    "kind": district.kind,
                    "parent": district.parent,
                    "name": {
                        "sr-Cyrl": sr_cyrl,
                        "sr-Latn": sr_latn,
                        "ru": district.ru or tags.get("name:ru") or russian(sr_cyrl),
                        "en": _latin(tags, "name:en") or sr_latn,
                    },
                    "aliases": list(district.aliases),
                    "center": [round(center.x, 6), round(center.y, 6)],
                    "source": f"osm:{district.osm}",
                },
                "geometry": mapping(shape),
            }
        )
    return {
        "type": "FeatureCollection",
        "city": {"slug": city, "name": CITY_NAMES[city]},
        "attribution": ATTRIBUTION,
        "features": features,
    }


def main() -> int:
    city = sys.argv[1] if len(sys.argv) > 1 else "novi-sad"
    raw = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    collection = build(city, raw)
    target = Path(__file__).resolve().parents[1] / "geo" / f"{city}.geojson"
    text = json.dumps(collection, ensure_ascii=False, separators=(",", ":"))
    target.write_text(
        text.replace('{"type":"Feature"', '\n{"type":"Feature"') + "\n", encoding="utf-8"
    )
    sys.stdout.write(
        f"{target.name}: {len(collection['features'])} districts, {len(text) // 1024} KB\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
