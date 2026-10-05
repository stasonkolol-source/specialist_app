"""Настоящие фото и аватары для `cli seed-demo` из локального кэша (scripts/demo-media/fetch.py).

Кэш — `backend/.cache/demo-media/` с `index.json`: фото работ (portfolio) по категориям сида,
фото «проблем» к заявкам (job) по категории и предмету — течёт кран, пыль после ремонта — и
рисованные аватары DiceBear (avatar) по полу. Кэша нет или он пуст — `DemoMedia.load` даёт None,
и сид кладёт прежние цветные заглушки: CI и тестам сеть не нужна.

Одно фото работы достаётся нескольким демо-специалистам одной категории, а media ищет у фото
портфолио почти такие же у других аккаунтов (pHash, 7.6) и открывает кейс «фейковое портфолио».
Поэтому каждый следующий показ фото — другой кадр: отражение и кадрирование, пока pHash не
отойдёт от всех уже загруженных в этот запуск дальше порога media (`unique_variant`).
"""

import io
import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from PIL import Image, ImageOps

from app.entrypoints._seed_demo_content import Lang
from app.modules.media.domain.asset import DUPLICATE_DISTANCE
from app.modules.media.infrastructure.phash import distance, perceptual_hash

CACHE: Final = Path(__file__).resolve().parents[3] / ".cache" / "demo-media"
"""Кэш по умолчанию — backend/.cache/demo-media (в образе backend его нет: там — заглушки)."""
MAX_SIDE: Final = 1600
CROPS: Final = (
    (0.0, 0.0, 1.0, 1.0),
    (0.0, 0.0, 0.8, 0.8),
    (0.2, 0.2, 1.0, 1.0),
    (0.0, 0.2, 0.8, 1.0),
    (0.2, 0.0, 1.0, 0.8),
    (0.1, 0.1, 0.9, 0.9),
)
"""Кадрирование (доли ширины и высоты: слева, сверху, справа, снизу) — вместе с отражением
двенадцать кадров одного фото; подходит первый с pHash дальше порога от всех взятых."""
FAR_ENOUGH: Final = DUPLICATE_DISTANCE + 4
"""С запасом от порога media: его обработка пересжимает кадр, и хэш чуть сдвигается."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MediaFile:
    id: str
    purpose: str
    path: Path
    mime: str
    category: str | None = None
    subject: str | None = None
    gender: str | None = None
    caption: dict[Lang, str] | None = None


@dataclass(frozen=True, slots=True)
class DemoMedia:
    portfolio: dict[str, tuple[MediaFile, ...]]
    """Фото работ по slug категории."""
    jobs: dict[tuple[str, str], tuple[MediaFile, ...]]
    """Фото к заявке по (категория, предмет — DemoJob.photos)."""
    avatars: dict[str, tuple[MediaFile, ...]]
    """Аватары по полу: f и m."""

    @classmethod
    def load(cls, root: Path) -> DemoMedia | None:
        """Кэш `root`; нет index.json или ни одного файла из него — None (заглушки)."""
        try:
            rows = json.loads((root / "index.json").read_text(encoding="utf-8"))["files"]
        except OSError, ValueError, KeyError, TypeError:
            return None
        portfolio: dict[str, list[MediaFile]] = {}
        jobs: dict[tuple[str, str], list[MediaFile]] = {}
        avatars: dict[str, list[MediaFile]] = {}
        for row in rows if isinstance(rows, list) else ():
            item = _file(root, row)
            if item is None:
                continue
            if item.purpose == "portfolio" and item.category and item.caption:
                portfolio.setdefault(item.category, []).append(item)
            elif item.purpose == "job" and item.category and item.subject:
                jobs.setdefault((item.category, item.subject), []).append(item)
            elif item.purpose == "avatar" and item.gender in ("f", "m"):
                avatars.setdefault(item.gender, []).append(item)
        if not (portfolio or jobs or avatars):
            return None
        return cls(
            portfolio={key: tuple(value) for key, value in portfolio.items()},
            jobs={key: tuple(value) for key, value in jobs.items()},
            avatars={key: tuple(value) for key, value in avatars.items()},
        )

    @property
    def size(self) -> int:
        pools = (self.portfolio, self.jobs, self.avatars)
        return sum(len(files) for pool in pools for files in pool.values())


def _file(root: Path, row: object) -> MediaFile | None:
    """Строка index.json; битая или без файла на диске — None (кэш докачается позже)."""
    if not isinstance(row, dict):
        return None
    path = (root / str(row.get("file", ""))).resolve()
    mime = row.get("mime")
    if mime not in ("image/jpeg", "image/png") or root.resolve() not in path.parents:
        return None  # только картинки и только внутри кэша
    if not path.is_file():
        return None
    caption = row.get("caption")
    return MediaFile(
        id=str(row.get("id")),
        purpose=str(row.get("purpose")),
        path=path,
        mime=str(mime),
        category=row.get("category"),
        subject=row.get("subject"),
        gender=row.get("gender"),
        caption=(
            {"ru": str(caption["ru"]), "sr": str(caption["sr"])}
            if isinstance(caption, dict) and caption.get("ru") and caption.get("sr")
            else None
        ),
    )


@dataclass(slots=True)
class PortfolioFrames:
    """pHash всех фото работ, загруженных в этот запуск: новое фото — дальше порога от каждого."""

    taken: list[int] = field(default_factory=list)

    def unique_variant(self, source: Path) -> bytes | None:
        """JPEG-кадр фото, непохожий (по pHash media) на всё уже взятое; None — у фото кадры
        кончились, специалисту достанется другое."""
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
        for frame in _frames(image):
            body = _jpeg(frame)
            with Image.open(io.BytesIO(body)) as decoded:  # хэш — как его посчитает media
                phash = perceptual_hash(decoded)
            if all(distance(phash, other) > FAR_ENOUGH for other in self.taken):
                self.taken.append(phash)
                return body
        return None


def _frames(image: Image.Image) -> Iterator[Image.Image]:
    width, height = image.size
    for mirrored in (False, True):
        base = ImageOps.mirror(image) if mirrored else image
        for left, top, right, bottom in CROPS:
            box = (int(left * width), int(top * height), int(right * width), int(bottom * height))
            yield base.crop(box) if box != (0, 0, width, height) else base


def _jpeg(image: Image.Image) -> bytes:
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=85)
    return out.getvalue()


def pick[T](pool: Sequence[T], count: int, start: int) -> list[T]:
    """`count` файлов пула подряд с места `start` по кругу — без повторов, пока пул не кончится."""
    return [pool[(start + index) % len(pool)] for index in range(min(count, len(pool)))]
