"""Карта Нови-Сада для выбора точки в заявке (M2a, Q28 вариант A): тайлы, шрифты подписей, спрайт.

Всё — с официальных источников Protomaps, версии закреплены ниже, повторный запуск даёт то же:
- novi-sad.pmtiles — вырезка из ежедневной сборки Protomaps (build.protomaps.com/<дата>.pmtiles)
  командой `pmtiles extract` в официальном образе protomaps/go-pmtiles: рамка города из
  backend/seeds/geo/novi-sad.geojson плюс MARGIN_KM, зумы 0–MAXZOOM;
- fonts/<fontstack>/<начало>-<конец>.pbf — глифы шрифтов стиля @protomaps/basemaps из
  protomaps/basemaps-assets на закреплённом коммите: латиница с расширениями, кириллица, знаки
  препинания (остальные диапазоны MapLibre рисует системным шрифтом сам);
- sprites/v4/<flavor>{,@2x}.{json,png} — иконки и щиты стиля v4 оттуда же;
- provenance.json — источники, даты, лицензии, рамка, sha256 файлов. Подпись на карте
  (© OpenStreetMap, Protomaps) обязательна — scripts/map/README.md.

Запуск: python3 scripts/map/build.py [--out DIR] [--build YYYYMMDD] [--force] [--dev]
Нужны git и Docker. Готовый каталог с теми же входами не пересобирается (--force — пересобрать).
--dev (make map-assets): ещё и VITE_MAP_ASSETS_URL=/map в apps/tma/.env, если там пусто.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "backend" / "seeds" / "geo" / "novi-sad.geojson"
DEV_OUT = ROOT / "apps" / "tma" / "public" / "map"
DEV_URL = "/map"
TILES = "novi-sad.pmtiles"
PROVENANCE = "provenance.json"

# Сборка Protomaps: архив хранит все сборки последней недели и последнюю сборку каждой
# patch-версии (docs.protomaps.com/basemaps/downloads). 20260811 — последняя 4.15.1, она не
# пропадёт; свежая неделя исчезнет через 7 дней, и make map-assets на новом Маке перестанет
# собираться. Обновление — README.md, «Новая сборка».
PROTOMAPS_BUILD = "20260811"
BUILDS_URL = "https://build.protomaps.com/{build}.pmtiles"
BUILDS_INDEX = "https://build-metadata.protomaps.dev/builds.json"
EXTRACT_IMAGE = (
    "protomaps/go-pmtiles:v1.31.2"
    "@sha256:06574f01f55a78f78f887bc7ebf729a5c093c0d6e17d9876300cfcb0758b59d3"
)
MAXZOOM = 15
MARGIN_KM = 5.0

# Шрифты и спрайты: тегов и релизов у репозитория нет — закреплён коммит (main, 2025-10-31).
# git проверяет, что получен ровно этот коммит.
ASSETS_REPO = "https://github.com/protomaps/basemaps-assets.git"
ASSETS_COMMIT = "028c18f713baecad011301ff7a69acc39bcc2ae7"
FONTSTACKS = ("Noto Sans Regular", "Noto Sans Medium", "Noto Sans Italic")
GLYPH_RANGES = (
    0,  # Basic Latin, Latin-1
    256,  # Latin Extended-A: č ć đ š ž, венгерские ő ű
    512,  # Latin Extended-B: румынские ș ț
    768,  # комбинируемые диакритики (ударения), греческий
    1024,  # кириллица: ђ ј љ њ ћ џ, русинские є ї ґ
    1280,  # кириллица дополнительная
    7680,  # Latin Extended Additional
    8192,  # пунктуация: – — „ “ ” ’ … и валюты
    8448,  # буквоподобные и стрелки: №, ℃
)
SPRITE_FLAVORS = ("light", "dark", "white", "grayscale", "black")

ATTRIBUTION = (
    '<a href="https://www.openstreetmap.org/copyright">© OpenStreetMap</a>, '
    '<a href="https://protomaps.com">Protomaps</a>'
)
LICENSES = {
    "tiles": "© OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright): "
    "Produced Work, attribution required; Protomaps basemap, BSD-3-Clause "
    "(https://github.com/protomaps/basemaps)",
    "fonts": "Noto Sans, SIL Open Font License 1.1 (fonts/OFL.txt)",
    "sprites": "derived from tangrams/icons, MIT "
    "(https://github.com/tangrams/icons/blob/master/LICENSE.md)",
}


def log(message: str) -> None:
    sys.stdout.write(f"map: {message}\n")


def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, text=True, **kwargs)  # noqa: S603 — фиксированные команды


def city_bbox(seed: Path = SEED, margin_km: float = MARGIN_KM) -> list[float]:
    """Рамка всех полигонов сида (город и районы) плюс margin_km с каждой стороны.

    Долготный запас считается по северному краю — там градус короче всего, поэтому запас не
    меньше margin_km по всей рамке. Края округлены наружу до 1e-4° (~10 м)."""
    lons: list[float] = []
    lats: list[float] = []

    def walk(coords: list[object]) -> None:
        if coords and isinstance(coords[0], (int, float)):
            lons.append(float(coords[0]))
            lats.append(float(coords[1]))  # type: ignore[arg-type]
        else:
            for item in coords:
                walk(item)  # type: ignore[arg-type]

    for feature in json.loads(seed.read_text(encoding="utf-8"))["features"]:
        walk(feature["geometry"]["coordinates"])
    dlat = margin_km / 111.32
    north = max(lats) + dlat
    dlon = margin_km / (111.32 * math.cos(math.radians(north)))
    return [
        math.floor((min(lons) - dlon) * 1e4) / 1e4,
        math.floor((min(lats) - dlat) * 1e4) / 1e4,
        math.ceil((max(lons) + dlon) * 1e4) / 1e4,
        math.ceil(north * 1e4) / 1e4,
    ]


def inputs(build: str) -> dict[str, object]:
    """Всё, от чего зависит результат: совпало с provenance.json — пересобирать нечего."""
    return {
        "protomaps_build": build,
        "bbox": city_bbox(),
        "margin_km": MARGIN_KM,
        "maxzoom": MAXZOOM,
        "extract_image": EXTRACT_IMAGE,
        "basemaps_assets": {"repo": ASSETS_REPO, "commit": ASSETS_COMMIT},
        "fontstacks": list(FONTSTACKS),
        "glyph_ranges": [f"{start}-{start + 255}" for start in GLYPH_RANGES],
        "sprite_flavors": list(SPRITE_FLAVORS),
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def up_to_date(out: Path, wanted: dict[str, object]) -> bool:
    """Каталог собран из тех же входов и файлы не тронуты (размер и sha256 из provenance.json)."""
    try:
        provenance = json.loads((out / PROVENANCE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if provenance.get("inputs") != wanted:
        return False
    files = provenance.get("files", {})
    return bool(files) and all(
        (out / name).is_file()
        and (out / name).stat().st_size == meta["bytes"]
        and sha256(out / name) == meta["sha256"]
        for name, meta in files.items()
    )


def build_info(build: str) -> dict[str, object]:
    """Сборка из индекса Protomaps: версия схемы тайлов, дата, BLAKE3 исходного архива."""
    request = urllib.request.Request(BUILDS_INDEX, headers={"User-Agent": "sosed-map-build"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 — https-адрес
        builds = json.load(response)
    for item in builds:
        if item.get("key") == f"{build}.pmtiles":
            return {
                "url": BUILDS_URL.format(build=build),
                "version": item.get("version"),
                "uploaded": item.get("uploaded"),
                "b3sum": item.get("b3sum"),
            }
    # сборку удалили (старше недели и не последняя в patch-версии) — подсказать живые
    by_version: dict[str, str] = {}
    for item in builds:
        by_version[str(item.get("version"))] = str(item.get("key", "")).removesuffix(".pmtiles")
    kept = ", ".join(f"{key} ({version})" for version, key in list(by_version.items())[-6:])
    sys.exit(f"map: build {build} is not in {BUILDS_INDEX}; recent kept builds: {kept}")


def docker(*args: str, mount: Path) -> subprocess.CompletedProcess[str]:
    # свой uid: на Linux (CI) файл иначе достался бы root
    cmd = [
        "docker",
        "run",
        "--rm",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "-v",
        f"{mount}:/out",
        EXTRACT_IMAGE,
        *args,
    ]
    try:
        return run(cmd, capture_output=True)
    except subprocess.CalledProcessError as exc:
        sys.exit(f"map: pmtiles {args[0]} failed ({exc.returncode}):\n{exc.stderr.strip()}")


def extract_tiles(work: Path, build: str, bbox: list[float]) -> dict[str, object]:
    """pmtiles extract: из планеты качаются только нужные диапазоны байт (HTTP Range)."""
    started = time.monotonic()
    docker(
        "extract",
        BUILDS_URL.format(build=build),
        f"/out/{TILES}",
        "--bbox=" + ",".join(f"{value:.4f}" for value in bbox),
        f"--maxzoom={MAXZOOM}",
        mount=work,
    )
    docker("verify", f"/out/{TILES}", mount=work)
    header = json.loads(docker("show", f"/out/{TILES}", "--header-json", mount=work).stdout)
    metadata = json.loads(docker("show", f"/out/{TILES}", "--metadata", mount=work).stdout)
    log(
        f"{TILES}: {(work / TILES).stat().st_size / 2**20:.1f} MiB "
        f"in {time.monotonic() - started:.0f} s"
    )
    return {"header": header, "attribution": metadata.get("attribution")}


def fetch_assets(work: Path) -> None:
    """Шрифты и спрайты из basemaps-assets на ASSETS_COMMIT: partial clone без лишних blob'ов."""
    fonts = [
        f"fonts/{stack}/{start}-{start + 255}.pbf" for stack in FONTSTACKS for start in GLYPH_RANGES
    ]
    sprites = [
        f"sprites/v4/{flavor}{scale}.{ext}"
        for flavor in SPRITE_FLAVORS
        for scale in ("", "@2x")
        for ext in ("json", "png")
    ]
    paths = [*fonts, "fonts/OFL.txt", *sprites]
    git = [
        "git",
        "-c",
        "init.defaultBranch=main",
        "-c",
        "core.autocrlf=false",
        "-c",
        "advice.detachedHead=false",
    ]
    with tempfile.TemporaryDirectory(prefix="basemaps-assets-") as clone:
        run([*git, "init", "-q", clone])
        run(
            [
                *git,
                "-C",
                clone,
                "fetch",
                "-q",
                "--depth=1",
                "--filter=blob:none",
                ASSETS_REPO,
                ASSETS_COMMIT,
            ]
        )
        run([*git, "-C", clone, "checkout", "-q", ASSETS_COMMIT, "--", *paths])
        for path in paths:
            target = work / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(clone) / path, target)
    log(f"fonts and sprites: {len(paths)} files from basemaps-assets@{ASSETS_COMMIT[:7]}")


def enable_dev() -> None:
    """VITE_MAP_ASSETS_URL=/map в apps/tma/.env, если переменной нет или она пуста: стенд
    (vite build + preview) отдаёт public/map с того же origin, Range умеет (sirv)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from envfile import read, update  # общий помощник scripts/ (envfile.py)

    env = ROOT / "apps" / "tma" / ".env"
    if read(env).get("VITE_MAP_ASSETS_URL"):
        log("apps/tma/.env: VITE_MAP_ASSETS_URL already set")
        return
    update(env, {"VITE_MAP_ASSETS_URL": DEV_URL}, overwrite=True)
    log(f"apps/tma/.env: VITE_MAP_ASSETS_URL={DEV_URL}; make dev-restart — стенд соберёт карту")


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEV_OUT, help="каталог результата")
    parser.add_argument("--build", default=PROTOMAPS_BUILD, help="сборка Protomaps YYYYMMDD")
    parser.add_argument("--force", action="store_true", help="пересобрать, даже если готово")
    parser.add_argument("--dev", action="store_true", help="включить карту в apps/tma/.env")
    args = parser.parse_args()
    out: Path = args.out.resolve()
    wanted = inputs(args.build)

    if not args.force and up_to_date(out, wanted):
        log(f"{out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}: up to date")
    else:
        for tool in ("git", "docker"):
            if shutil.which(tool) is None:
                sys.exit(f"map: {tool} is required")
        started = time.monotonic()
        source = build_info(args.build)
        out.parent.mkdir(parents=True, exist_ok=True)
        # сборка — в соседний скрытый каталог, затем подмена целиком: стенд не видит половину
        work = Path(tempfile.mkdtemp(prefix=".map-build-", dir=out.parent))
        work.chmod(0o755)  # mkdtemp даёт 0700, а каталог читают сервер стенда и загрузка
        try:
            tiles = extract_tiles(work, args.build, wanted["bbox"])  # type: ignore[arg-type]
            fetch_assets(work)
            files = {
                path.relative_to(work).as_posix(): {
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
                for path in sorted(work.rglob("*"))
                if path.is_file()
            }
            provenance = {
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "inputs": wanted,
                "source": {"tiles": source},
                "tiles": tiles,
                "attribution": ATTRIBUTION,
                "licenses": LICENSES,
                "files": files,
            }
            (work / PROVENANCE).write_text(
                json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            old = out.with_name(f".map-old-{os.getpid()}")
            if out.exists():
                out.rename(old)
            work.rename(out)
            shutil.rmtree(old, ignore_errors=True)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        total = sum(meta["bytes"] for meta in files.values()) / 2**20
        log(f"{out}: {len(files) + 1} files, {total:.1f} MiB, {time.monotonic() - started:.0f} s")
    if args.dev:
        enable_dev()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
