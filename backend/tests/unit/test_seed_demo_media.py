"""`cli seed-demo` с настоящими фото (scripts/demo-media): манифест — только свободные лицензии и
полная атрибуция, кэша нет — заглушки, кадры одного фото у разных специалистов не совпадают по
pHash media, история отзывов — правдоподобная (новички без отзывов, у популярных — десятки,
оценки в основном 4–5, даты — в прошлом)."""

import importlib.util
import io
import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
from PIL import Image, ImageDraw

from app.entrypoints._seed_demo import (
    SCALES,
    SeedClock,
    history,
    plan,
    review_text,
)
from app.entrypoints._seed_demo_content import (
    CATEGORIES,
    CATEGORY_REVIEWS,
    JOBS,
    PRE_PLATFORM,
    REPLIES,
    REVIEW_TEXTS,
)
from app.entrypoints._seed_demo_media import DemoMedia, PortfolioFrames, pick
from app.modules.media.domain.asset import DUPLICATE_DISTANCE
from app.modules.media.infrastructure.phash import distance, perceptual_hash

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3]
CYRILLIC = re.compile(r"[Ѐ-ӿ]")
NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


def fetch_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "demo_media_fetch", ROOT / "scripts" / "demo-media" / "fetch.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manifest() -> dict[str, list[dict[str, object]]]:
    data = json.loads((ROOT / "scripts" / "demo-media" / "manifest.json").read_text())
    assert isinstance(data, dict)
    return data


def test_manifest_has_only_free_licences_and_full_attribution() -> None:
    fetch, data = fetch_script(), manifest()

    assert fetch.check_manifest(data) == []
    files = data["files"]
    assert all(entry.get("sha256") for entry in files)  # список закреплён
    assert {str(entry["license"]) for entry in files} <= set(fetch.LICENSES)
    assert not any(
        "NC" in str(entry["license"]) or "ND" in str(entry["license"]) for entry in files
    )


def test_manifest_covers_every_category_and_job_subject() -> None:
    files = manifest()["files"]
    portfolio = Counter(str(e["category"]) for e in files if e["purpose"] == "portfolio")
    subjects = {(str(e["category"]), str(e["subject"])) for e in files if e["purpose"] == "job"}
    avatars = Counter(str(e["gender"]) for e in files if e["purpose"] == "avatar")

    assert set(portfolio) == {category.slug for category in CATEGORIES}
    assert min(portfolio.values()) >= 6  # 6–12 работ на категорию
    for job in JOBS:  # предмет фото заявки — из манифеста, иначе фото у неё не будет
        if job.photos is not None:
            assert (job.category, job.photos) in subjects, job.title["ru"]
    assert avatars["f"] >= 25  # на 60 специалистов без повторов
    assert avatars["m"] >= 25


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"license": "CC-BY-NC-2.0"}, "белого списка"),
        ({"license": "CC-BY-ND-4.0"}, "белого списка"),
        ({"author": ""}, "нет поля author"),
        ({"source": None}, "нет поля source"),
        ({"url": "http://live.staticflickr.com/1/2_b.jpg"}, "не https"),
        ({"url": "https://example.com/photo.jpg"}, "только с"),
        ({"caption": {"ru": "Кухня"}}, "caption"),
        ({"category": None}, "category"),
        ({"sha256": "abc"}, "sha256"),
        ({"purpose": "message"}, "purpose"),
    ],
)
def test_manifest_check_catches_broken_entries(change: dict[str, object], problem: str) -> None:
    entry = {
        "id": "plumbing-p99",
        "purpose": "portfolio",
        "category": "plumbing",
        "caption": {"ru": "Новый смеситель", "sr": "Nova slavina"},
        "source": "https://www.flickr.com/photos/someone/1",
        "url": "https://live.staticflickr.com/1/2_b.jpg",
        "author": "someone",
        "license": "CC-BY-2.0",
    }
    fetch = fetch_script()

    assert fetch.check_manifest({"files": [entry]}) == []
    problems = fetch.check_manifest({"files": [{**entry, **change}]})
    assert any(problem in text for text in problems), problems


def test_avatars_are_drawn_cc0_only() -> None:
    fetch = fetch_script()
    avatar = {
        "id": "avatar-f-01",
        "purpose": "avatar",
        "gender": "f",
        "source": "https://www.dicebear.com/styles/notionists/",
        "url": "https://api.dicebear.com/9.x/notionists/png?seed=1",
        "author": "Zoish",
        "license": "CC0-1.0",
    }

    assert fetch.check_manifest({"files": [avatar]}) == []
    photo = {**avatar, "url": "https://live.staticflickr.com/1/2_b.jpg"}  # лицо настоящего
    assert fetch.check_manifest({"files": [photo]}) != []
    assert fetch.check_manifest({"files": [{**avatar, "license": "CC-BY-4.0"}]}) != []
    assert fetch.check_manifest({"files": [avatar, avatar]}) == [
        "files[1] avatar-f-01: id повторяется"
    ]


def test_fetch_reads_jpeg_and_png_sizes() -> None:
    fetch = fetch_script()

    assert fetch.image_info(jpeg((1024, 683), 1))[2:] == (1024, 683)
    assert fetch.image_info(b"\xff\xd8\xff\xff" + jpeg((640, 480), 2)[2:])[2:] == (640, 480)
    png = io.BytesIO()
    Image.new("RGB", (256, 256)).save(png, format="PNG")
    assert fetch.image_info(png.getvalue()) == ("image/png", "png", 256, 256)
    with pytest.raises(ValueError, match="JPEG"):
        fetch.image_info(b"RIFF....WEBP")


def jpeg(size: tuple[int, int], seed: int) -> bytes:
    """Фото-заглушка с крупными фигурами: у разных seed — разный pHash."""
    image = Image.new("RGB", size, (200, 180, 150))
    draw = ImageDraw.Draw(image)
    width, height = size
    for index in range(6):
        x = (seed * 97 + index * 211) % width
        y = (seed * 53 + index * 157) % height
        draw.rectangle((x, y, x + width // 3, y + height // 4), fill=(30 * index, 90, 160 - seed))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=90)
    return out.getvalue()


def fake_cache(root: Path) -> Path:
    """Крошечный кэш, как после fetch.py: два фото работ, одно фото заявки, один аватар."""
    rows: list[dict[str, object]] = []
    for name, purpose, extra in (
        (
            "plumbing-p01",
            "portfolio",
            {"category": "plumbing", "caption": {"ru": "Кран", "sr": "Slavina"}},
        ),
        (
            "plumbing-p02",
            "portfolio",
            {"category": "plumbing", "caption": {"ru": "Бойлер", "sr": "Bojler"}},
        ),
        ("plumbing-j01", "job", {"category": "plumbing", "subject": "tap"}),
    ):
        path = root / purpose / f"{name}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(jpeg((800, 600), len(rows) + 1))
        rows.append(
            {
                "id": name,
                "purpose": purpose,
                "file": f"{purpose}/{name}.jpg",
                "mime": "image/jpeg",
                **extra,
            }
        )
    avatar = root / "avatar" / "avatar-f-01.png"
    avatar.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (256, 256), (255, 213, 220)).save(avatar, format="PNG")
    rows.append(
        {
            "id": "avatar-f-01",
            "purpose": "avatar",
            "gender": "f",
            "file": "avatar/avatar-f-01.png",
            "mime": "image/png",
        }
    )
    (root / "index.json").write_text(json.dumps({"version": 1, "files": rows}))
    return root


def test_no_cache_means_placeholders(tmp_path: Path) -> None:
    assert DemoMedia.load(tmp_path / "missing") is None
    (tmp_path / "index.json").write_text("{not json")
    assert DemoMedia.load(tmp_path) is None
    (tmp_path / "index.json").write_text(json.dumps({"files": []}))
    assert DemoMedia.load(tmp_path) is None


def test_cache_groups_files_and_skips_missing_ones(tmp_path: Path) -> None:
    root = fake_cache(tmp_path)
    index = json.loads((root / "index.json").read_text())
    index["files"] += [
        {
            "id": "gone",
            "purpose": "portfolio",
            "category": "nails",
            "file": "portfolio/gone.jpg",
            "mime": "image/jpeg",
            "caption": {"ru": "Френч", "sr": "Francuski"},
        },
        {
            "id": "escape",
            "purpose": "avatar",
            "gender": "m",
            "file": "../outside.png",
            "mime": "image/png",
        },
    ]
    (tmp_path.parent / "outside.png").write_bytes(b"\x89PNG")
    (root / "index.json").write_text(json.dumps(index))

    media = DemoMedia.load(root)

    assert media is not None
    assert [item.id for item in media.portfolio["plumbing"]] == ["plumbing-p01", "plumbing-p02"]
    assert media.portfolio["plumbing"][0].caption == {"ru": "Кран", "sr": "Slavina"}
    assert [item.id for item in media.jobs[("plumbing", "tap")]] == ["plumbing-j01"]
    assert [item.id for item in media.avatars["f"]] == ["avatar-f-01"]
    assert "nails" not in media.portfolio  # файла нет
    assert "m" not in media.avatars  # путь вне кэша
    assert media.size == 4


def test_every_reuse_of_a_photo_is_another_frame_for_media(tmp_path: Path) -> None:
    root = fake_cache(tmp_path)
    frames = PortfolioFrames()
    bodies = [frames.unique_variant(root / "portfolio" / "plumbing-p01.jpg") for _ in range(4)]

    assert all(body is not None for body in bodies)
    hashes = [perceptual_hash(Image.open(io.BytesIO(body))) for body in bodies if body]
    for index, first in enumerate(hashes):
        for second in hashes[index + 1 :]:
            assert distance(first, second) > DUPLICATE_DISTANCE  # media не увидит дубликата
    assert all(Image.open(io.BytesIO(body)).format == "JPEG" for body in bodies if body)


def test_pick_takes_different_files_until_the_pool_ends() -> None:
    pool = ("a", "b", "c", "d")

    assert pick(pool, 3, start=2) == ["c", "d", "a"]
    assert pick(pool, 9, start=1) == ["b", "c", "d", "a"]


def test_review_counts_look_like_a_real_catalog() -> None:
    demos = [plan(number) for number in range(SCALES["small"].specialists)]
    counts = [demo.reviews for demo in demos]

    newcomers = sum(count == 0 for count in counts)
    popular = [count for count in counts if count >= 13]
    assert 5 <= newcomers <= 20  # новички без отзывов
    assert popular  # популярные — десятки отзывов
    assert max(counts) <= 40
    assert sum(3 <= count <= 12 for count in counts) >= len(counts) // 2  # у большинства 3–12
    assert any(demo.pre_platform for demo in demos)
    assert 0.7 <= sum(demo.avatar for demo in demos) / len(demos) < 1  # кто-то — с инициалами


def test_history_is_in_the_past_and_mostly_positive() -> None:
    small = SCALES["small"]
    clients = range(small.start + small.clients, small.start + small.clients + small.past_clients)
    deals = [deal for n in range(small.specialists) for deal in history(plan(n), clients, NOW)]
    ratings = Counter(deal.rating for deal in deals)

    assert len(deals) == sum(plan(n).reviews for n in range(small.specialists))
    assert ratings[5] + ratings[4] >= 0.85 * len(deals)
    assert ratings[3] > 0
    assert all(deal.client in clients for deal in deals)
    assert all(NOW - timedelta(days=301) <= deal.at <= NOW - timedelta(days=2) for deal in deals)
    assert len({deal.at.month for deal in deals}) >= 8  # месяцы отзывов разные
    texts = [deal.body for deal in deals if deal.body]
    assert len(set(texts)) >= 60  # большой пул, не одни и те же три фразы
    assert 0.2 <= sum(deal.reply is not None for deal in deals) / len(texts) <= 0.5
    assert all(CYRILLIC.search(text) for text in texts)
    first = history(plan(7), clients, NOW)
    assert [deal.at for deal in first] == sorted(deal.at for deal in first)
    assert first == history(plan(7), clients, NOW)  # детерминированно


def test_review_texts_are_concrete_and_neutral() -> None:
    import random

    rng = random.Random(1)  # noqa: S311 — тест
    plumbing = {review_text(rng, "ru", 5, "plumbing") for _ in range(200)}
    assert plumbing & set(CATEGORY_REVIEWS["plumbing"][5])
    assert {review_text(rng, "sr", 5, "plumbing") for _ in range(50)} <= set(REVIEW_TEXTS["sr"][5])
    assert set(CATEGORY_REVIEWS) == {category.slug for category in CATEGORIES}
    russian = [
        text for pool in CATEGORY_REVIEWS.values() for texts in pool.values() for text in texts
    ]
    russian += [text for texts in REVIEW_TEXTS["ru"].values() for text in texts]
    # отзыв пишет и мужчина, и женщина, а мастер бывает обоих полов: без «остался доволен»
    gendered = re.compile(r"\b(остал(ся|ась)|доволен|довольна|пришёл|пришла|сделал|сделала)\b")
    assert [text for text in russian if gendered.search(text.lower())] == []
    serbian = [*REVIEW_TEXTS["sr"].values(), *REPLIES["sr"].values(), PRE_PLATFORM["sr"]]
    assert not any(CYRILLIC.search(text) for texts in serbian for text in texts)


def test_seed_clock_travels_only_inside_at() -> None:
    clock = SeedClock()
    past = NOW - timedelta(days=100)

    with clock.at(past):
        assert clock.now() == past
    assert clock.now() > past + timedelta(days=99)
