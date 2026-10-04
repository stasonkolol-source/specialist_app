"""Вердикт по изображению после omni-moderation (ADR-0016 §3–4, ARCHITECTURE §10.3, §14.1;
DEVELOPMENT_PLAN 6.7).

omni-moderation по картинке оценивает только шесть категорий: `sexual`, `violence`,
`violence/graphic` и три `self-harm*` (остальные — только у текста, у картинки их оценка
не считается). Пороги — свои, по категориям, а не только `flagged` провайдера: от них зависит,
скрыть ли фото сразу.
- BLOCK — P0: фото скрывается сразу (варианты уходят из публичного бакета), кейс в очередь
  safety (≤ 1 ч). Только там, где показывать фото даже минуту нельзя: откровенное, кровь и
  увечья, самоповреждение. Аккаунт автоматически не замораживается: классификатор картинок
  ошибается чаще словаря (скульптура, медицинский массаж, разделка мяса), санкцию ставит
  модератор.
- REVIEW — P2: фото остаётся, решает человек (≤ 30 мин). Сюда же `flagged` провайдера ниже наших
  порогов и проверка, которая не состоялась (`Unavailable`): ADR-0016 — без проверки в ручную
  очередь, а не «чисто».
- CLEAN — ничего не делать.
Пороги — **[Допущение]**, калибруются на бете по примерам K28: у ремонта и стройки бывает
`violence` от инструмента и разрушенных стен, у фото до и после — от пятен краски.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from app.modules.moderation.domain.queues import Queue
from app.platform.ai.port import ModerationResult, Unavailable

BLOCK_AT: Final[Mapping[str, float]] = MappingProxyType(
    {
        # откровенное фото на площадке услуг не бывает уместным: взрослых категорий нет
        "sexual": 0.8,
        # кровь и увечья крупно — даже у «до и после» ремонта так не бывает
        "violence/graphic": 0.8,
        # самоповреждение — риск для человека: модератор должен увидеть кейс в течение часа
        "self-harm": 0.8,
        "self-harm/intent": 0.8,
        "self-harm/instructions": 0.8,
    }
)
"""Оценка от порога — фото скрыть сразу и открыть кейс P0 (очередь safety)."""

REVIEW_AT: Final[Mapping[str, float]] = MappingProxyType(
    {
        "sexual": 0.4,
        # без «graphic» — драка, оружие в кадре, но и снос стены: только человек
        "violence": 0.7,
        "violence/graphic": 0.4,
        "self-harm": 0.4,
        "self-harm/intent": 0.4,
        "self-harm/instructions": 0.4,
    }
)
"""Оценка от порога (или `flagged` провайдера) — кейс P2: фото видно, решает модератор."""


class ImageAction(StrEnum):
    CLEAN = "clean"
    REVIEW = "review"
    BLOCK = "block"


@dataclass(frozen=True, slots=True, kw_only=True)
class ImageVerdict:
    action: ImageAction
    queue: Queue | None = None
    """Очередь кейса: REVIEW — premod, BLOCK — safety."""
    signals: tuple[str, ...] = ()
    """Что сработало — в повод кейса и журнал: категория и оценка, без самого фото."""
    labels: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))
    """Оценки категорий от порога REVIEW — в `media.assets.moderation_labels`."""
    reason_code: str | None = None
    """BLOCK: почему скрыто — код причины для кейса."""


REASON_CODES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "sexual": "sexual_content",
        "violence": "violence",
        "violence/graphic": "violence",
        "self-harm": "self_harm",
        "self-harm/intent": "self_harm",
        "self-harm/instructions": "self_harm",
    }
)
"""Категория omni → код причины (как у санкций: латиница, цифры, «_»)."""


UNCHECKED: Final = ImageVerdict(
    action=ImageAction.REVIEW, queue=Queue.PREMOD, signals=("image:unchecked",)
)
"""Проверка так и не состоялась (задача падала, вариант не прочитать): как `Unavailable` — без
проверки фото не считается чистым, решает модератор (P2, ADR-0016)."""


def judge_image(result: ModerationResult | Unavailable) -> ImageVerdict:
    """Что делать с фото по ответу omni-moderation."""
    if isinstance(result, Unavailable):
        return ImageVerdict(
            action=ImageAction.REVIEW,
            queue=Queue.PREMOD,
            signals=(f"image:unavailable:{result.reason.value}",),
        )
    scores = {category: score for category, score in result.scores.items() if category in REVIEW_AT}
    labels = {c: s for c, s in scores.items() if s >= REVIEW_AT[c]}
    blocked = sorted(
        (c for c, s in scores.items() if c in BLOCK_AT and s >= BLOCK_AT[c]),
        key=lambda c: -scores[c],
    )
    if blocked:
        return ImageVerdict(
            action=ImageAction.BLOCK,
            queue=Queue.SAFETY,
            signals=tuple(_signal(c, scores[c]) for c in blocked),
            labels=MappingProxyType(labels),
            reason_code=REASON_CODES[blocked[0]],
        )
    if labels:
        ordered = sorted(labels, key=lambda c: -labels[c])
        return ImageVerdict(
            action=ImageAction.REVIEW,
            queue=Queue.PREMOD,
            signals=tuple(_signal(c, labels[c]) for c in ordered),
            labels=MappingProxyType(labels),
        )
    if result.flagged:  # провайдер увидел то, чего не видят наши пороги, — пусть решит человек
        return ImageVerdict(
            action=ImageAction.REVIEW, queue=Queue.PREMOD, signals=("image:flagged",)
        )
    return ImageVerdict(action=ImageAction.CLEAN)


def _signal(category: str, score: float) -> str:
    return f"image:{category}:{score:.2f}"
