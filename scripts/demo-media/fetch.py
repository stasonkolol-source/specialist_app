"""Демо-медиа для `cli seed-demo`: настоящие фото работ и «проблем» в заявках и рисованные аватары.

Список закреплён в `manifest.json` рядом: у каждого файла — назначение (portfolio, job, avatar),
категория демо-сида, страница источника, прямая ссылка, автор, лицензия и sha256. Сами файлы в
git не попадают (репозиторий публичный): скрипт качает их в `backend/.cache/demo-media/` (в
.gitignore) и пишет там `index.json` — его читает seed-demo. Нет кэша — сид кладёт цветные
заглушки, как раньше: CI и тестам сеть не нужна.

Лицензии — только свободные для любого использования с указанием автора или без: CC0, Public
Domain Mark, CC BY и CC BY-SA (`LICENSES`); атрибуция — в манифесте и в `index.json`. Фото
найдены через Openverse (Flickr, StockSnap, WordPress Photos, Wikimedia Commons),
ссылки — уже уменьшенные до ≤ 1600 px варианты (Flickr `_b` — 1024 px, StockSnap — 960 px):
stdlib изображения не уменьшает, скрипт только проверяет размер. Аватары — DiceBear `notionists` (CC0): рисованные люди, а не
лица настоящих.

Только stdlib:
    python3 scripts/demo-media/fetch.py            # скачать недостающее, проверить sha256
    python3 scripts/demo-media/fetch.py --check    # только проверить манифест
    python3 scripts/demo-media/fetch.py --pin      # дописать sha256 новым файлам манифеста
Повторный запуск качает только отсутствующие или изменившиеся файлы.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).resolve().parent / "manifest.json"
DEST = ROOT / "backend" / ".cache" / "demo-media"
MAX_SIDE = 1600
USER_AGENT = "sosed-demo-media/1.0 (dev seed; https://github.com/stasonkolol-source)"

LICENSES = {
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "PDM-1.0": "https://creativecommons.org/publicdomain/mark/1.0/",
    "CC-BY-2.0": "https://creativecommons.org/licenses/by/2.0/",
    "CC-BY-2.5": "https://creativecommons.org/licenses/by/2.5/",
    "CC-BY-3.0": "https://creativecommons.org/licenses/by/3.0/",
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC-BY-SA-2.0": "https://creativecommons.org/licenses/by-sa/2.0/",
    "CC-BY-SA-2.5": "https://creativecommons.org/licenses/by-sa/2.5/",
    "CC-BY-SA-3.0": "https://creativecommons.org/licenses/by-sa/3.0/",
    "CC-BY-SA-4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
}
"""Белый список: свободные лицензии без запрета коммерции и переделок (без NC и ND)."""
PHOTO_HOSTS = (
    "live.staticflickr.com",
    "upload.wikimedia.org",
    "cdn.stocksnap.io",
    "pd.w.org",
)
HOSTS = {"portfolio": PHOTO_HOSTS, "job": PHOTO_HOSTS, "avatar": ("api.dicebear.com",)}
"""Откуда можно качать файл каждого назначения: аватары — только рисованные DiceBear."""
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MIME = {b"\xff\xd8\xff": ("image/jpeg", "jpg"), b"\x89PN": ("image/png", "png")}


def check_manifest(data: object) -> list[str]:
    """Что не так с манифестом — пусто, если всё в порядке."""
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        return ["manifest: нужен объект с массивом files"]
    problems: list[str] = []
    seen: set[str] = set()
    for index, entry in enumerate(data["files"]):
        name = entry.get("id") if isinstance(entry, dict) else None
        where = f"files[{index}] {name or ''}".strip()
        if not isinstance(entry, dict):
            problems.append(f"{where}: не объект")
            continue
        problems += [f"{where}: {problem}" for problem in _check_entry(entry)]
        if name in seen:
            problems.append(f"{where}: id повторяется")
        seen.add(str(name))
    return problems


def _check_entry(entry: dict[str, object]) -> list[str]:
    problems = []
    for key in ("id", "purpose", "source", "url", "author", "license"):
        if not isinstance(entry.get(key), str) or not str(entry[key]).strip():
            problems.append(f"нет поля {key}")
    if problems:
        return problems
    purpose = str(entry["purpose"])
    if not SLUG.match(str(entry["id"])):
        problems.append("id — только a-z, 0-9 и дефисы")
    if purpose not in HOSTS:
        return [*problems, f"purpose {purpose}: только {', '.join(HOSTS)}"]
    if entry["license"] not in LICENSES:
        problems.append(f"лицензия {entry['license']} не из белого списка")
    for key in ("source", "url"):
        if urlparse(str(entry[key])).scheme != "https":
            problems.append(f"{key} — не https")
    if urlparse(str(entry["url"])).hostname not in HOSTS[purpose]:
        problems.append(f"url {purpose} — только с {', '.join(HOSTS[purpose])}")
    sha = entry.get("sha256")
    if sha is not None and not (isinstance(sha, str) and SHA256.match(sha)):
        problems.append("sha256 — 64 шестнадцатеричных символа")
    if purpose == "avatar":
        if entry.get("gender") not in ("f", "m"):
            problems.append("у аватара gender — f или m")
        if entry["license"] != "CC0-1.0":
            problems.append("аватар — только CC0 (DiceBear notionists)")
        return problems
    if not isinstance(entry.get("category"), str) or not SLUG.match(str(entry["category"])):
        problems.append("нет category (slug листа демо-сида)")
    if purpose == "portfolio":
        caption = entry.get("caption")
        if not isinstance(caption, dict) or not all(
            isinstance(caption.get(lang), str) and 2 <= len(str(caption[lang])) <= 80
            for lang in ("ru", "sr")
        ):
            problems.append("у работы caption — ru и sr, 2–80 символов")
    elif not isinstance(entry.get("subject"), str) or not SLUG.match(str(entry["subject"])):
        problems.append("у фото заявки subject — slug проблемы (как DemoJob.photos)")
    return problems


def image_info(body: bytes) -> tuple[str, str, int, int]:
    """(MIME, расширение, ширина, высота) JPEG или PNG; иное — ValueError."""
    kind = MIME.get(body[:3])
    if kind is None:
        raise ValueError("не JPEG и не PNG")
    if kind[0] == "image/png":
        width, height = struct.unpack(">II", body[16:24])
        return (*kind, width, height)
    offset = 2
    while offset + 9 < len(body):
        if body[offset] != 0xFF:
            raise ValueError("битый JPEG")
        marker = body[offset + 1]
        if marker == 0xFF:  # байт-заполнитель перед маркером — так бывает
            offset += 1
            continue
        length = struct.unpack(">H", body[offset + 2 : offset + 4])[0]
        # SOF0–SOF15, кроме DHT (C4), JPG (C8) и DAC (CC): там размер кадра
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", body[offset + 5 : offset + 9])
            return (*kind, width, height)
        offset += 2 + length
    raise ValueError("у JPEG нет размера кадра")


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310 — https из манифеста
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        return bytes(response.read())


def fetch(entry: dict[str, object], dest: Path) -> tuple[dict[str, object] | None, str | None]:
    """(строка index.json, ошибка). Готовый файл с тем же sha256 не качается снова."""
    for existing in (dest / str(entry["purpose"])).glob(f"{entry['id']}.*"):
        body = existing.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if entry.get("sha256") in (None, digest):
            entry.setdefault("sha256", digest)
            return _row(entry, existing, dest, body), None
    try:
        body = download(str(entry["url"]))
        mime, ext, width, height = image_info(body)
    except (OSError, ValueError) as error:
        return None, f"{entry['id']}: {error}"
    digest = hashlib.sha256(body).hexdigest()
    if entry.get("sha256") not in (None, digest):
        return None, f"{entry['id']}: sha256 не совпал — файл у источника изменился"
    if max(width, height) > MAX_SIDE:
        return None, f"{entry['id']}: {width}×{height} — больше {MAX_SIDE} px, нужна ссылка поменьше"
    path = dest / str(entry["purpose"]) / f"{entry['id']}.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    entry.setdefault("sha256", digest)
    return _row(entry, path, dest, body, mime), None


def _row(
    entry: dict[str, object], path: Path, dest: Path, body: bytes, mime: str | None = None
) -> dict[str, object]:
    keys = ("id", "purpose", "category", "subject", "gender", "caption", "author", "license")
    row = {key: entry[key] for key in keys if key in entry}
    row["source"] = entry["source"]
    row["file"] = path.relative_to(dest).as_posix()
    row["mime"] = mime or image_info(body)[0]
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--dest", type=Path, default=DEST, help=f"куда класть (по умолчанию {DEST})")
    parser.add_argument("--check", action="store_true", help="только проверить манифест")
    parser.add_argument("--pin", action="store_true", help="дописать sha256 в манифест")
    args = parser.parse_args()
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    problems = check_manifest(data)
    unpinned = [entry["id"] for entry in data["files"] if "sha256" not in entry]
    if unpinned and not args.pin:
        problems.append(f"без sha256 ({len(unpinned)}): {', '.join(unpinned[:5])} — запустите --pin")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    if args.check:
        print(f"manifest: {len(data['files'])} файлов, ок")
        return 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda entry: fetch(entry, args.dest), data["files"]))
    rows = [row for row, _ in results if row is not None]
    errors = [error for _, error in results if error is not None]
    index = {"version": 1, "files": rows}
    args.dest.mkdir(parents=True, exist_ok=True)
    (args.dest / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    if args.pin:
        MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"demo-media: {len(rows)} файлов в {args.dest}, ошибок {len(errors)}")
    for error in errors:
        print(f"  {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
