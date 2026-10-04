"""Вердикт по фото после omni-moderation (DEVELOPMENT_PLAN 6.7, ADR-0016 §4): пороги категорий."""

import pytest

from app.modules.moderation.domain.images import (
    BLOCK_AT,
    REVIEW_AT,
    ImageAction,
    ImageVerdict,
    judge_image,
)
from app.modules.moderation.domain.queues import Queue
from app.platform.ai.port import ModerationResult, Unavailable, UnavailableReason

pytestmark = pytest.mark.unit

IMAGE_CATEGORIES = {
    "sexual",
    "self-harm",
    "self-harm/intent",
    "self-harm/instructions",
    "violence",
    "violence/graphic",
}
"""Категории, которые omni-moderation оценивает у фото (руководство OpenAI по модерации)."""


def scores(**values: float) -> ModerationResult:
    named = {key.replace("__", "/").replace("_", "-"): v for key, v in values.items()}
    return ModerationResult(flagged=any(v >= 0.5 for v in named.values()), scores=named)


def test_thresholds_cover_only_image_categories_and_block_is_stricter() -> None:
    assert set(REVIEW_AT) == IMAGE_CATEGORIES
    assert set(BLOCK_AT) <= set(REVIEW_AT)
    assert "violence" not in BLOCK_AT  # без «graphic» — только человек (стройка, снос)
    assert all(REVIEW_AT[c] < BLOCK_AT[c] for c in BLOCK_AT)


def test_clean_photo_needs_nothing() -> None:
    assert judge_image(scores(sexual=0.01, violence=0.2)) == ImageVerdict(action=ImageAction.CLEAN)


def test_text_only_categories_are_ignored_for_photos() -> None:
    # у фото провайдер их не оценивает; что бы ни пришло — не повод
    result = ModerationResult(flagged=False, scores={"sexual/minors": 0.99, "illicit": 0.99})
    assert judge_image(result).action is ImageAction.CLEAN


def test_violence_without_graphic_goes_to_a_human() -> None:
    """Ответ из руководства OpenAI (recorded/openai_moderation_flagged_image.json)."""
    verdict = judge_image(scores(violence=0.8599, violence__graphic=0.377))

    assert (verdict.action, verdict.queue) == (ImageAction.REVIEW, Queue.PREMOD)
    assert verdict.signals == ("image:violence:0.86",)
    assert dict(verdict.labels) == {"violence": 0.8599}
    assert verdict.reason_code is None


def test_explicit_photo_is_hidden_at_once_with_a_p0_case() -> None:
    verdict = judge_image(scores(sexual=0.97, violence=0.75))

    assert (verdict.action, verdict.queue, verdict.reason_code) == (
        ImageAction.BLOCK,
        Queue.SAFETY,
        "sexual_content",
    )
    assert verdict.signals == ("image:sexual:0.97",)
    assert set(verdict.labels) == {"sexual", "violence"}


def test_strongest_block_category_names_the_reason() -> None:
    verdict = judge_image(scores(violence__graphic=0.85, self_harm=0.95))
    assert verdict.reason_code == "self_harm"
    assert verdict.signals == ("image:self-harm:0.95", "image:violence/graphic:0.85")


def test_provider_flag_below_our_thresholds_still_goes_to_a_human() -> None:
    verdict = judge_image(ModerationResult(flagged=True, scores={"sexual": 0.3}))
    assert (verdict.action, verdict.signals) == (ImageAction.REVIEW, ("image:flagged",))


@pytest.mark.parametrize("reason", list(UnavailableReason))
def test_check_that_did_not_happen_goes_to_manual_queue(reason: UnavailableReason) -> None:
    """ADR-0016: без проверки фото не считается чистым — P2, но не скрывается."""
    verdict = judge_image(Unavailable(reason))
    assert (verdict.action, verdict.queue) == (ImageAction.REVIEW, Queue.PREMOD)
    assert verdict.signals == (f"image:unavailable:{reason.value}",)
