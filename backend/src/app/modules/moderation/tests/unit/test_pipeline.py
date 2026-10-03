"""Маршрут после автопроверок (ARCHITECTURE §14.1, DEVELOPMENT_PLAN 2.6)."""

from uuid import UUID

import pytest

from app.modules.moderation.domain.pipeline import (
    Checks,
    Route,
    Routing,
    needs_classifier,
    route,
    sampled,
)
from app.modules.moderation.domain.queues import Queue
from app.modules.moderation.domain.rules import (
    MatchSource,
    RuleAction,
    RuleCategory,
    RuleMatch,
    RulesVerdict,
)
from app.platform.ai.port import (
    ModerationResult,
    PolicyLabel,
    PolicyVerdict,
    Unavailable,
    UnavailableReason,
)

pytestmark = pytest.mark.unit

CLEAN_RULES = RulesVerdict()
CLEAN_OMNI = ModerationResult(flagged=False)
OK = PolicyVerdict(label=PolicyLabel.OK, confidence=0.95, explanation="")
NO_KEY = Unavailable(UnavailableReason.NO_KEY)


def rules(category: RuleCategory, action: RuleAction, evidence: str = "x") -> RulesVerdict:
    return RulesVerdict(
        (RuleMatch(source=MatchSource.RULE, category=category, action=action, evidence=evidence),)
    )


def verdict(label: PolicyLabel, confidence: float = 0.95) -> PolicyVerdict:
    return PolicyVerdict(label=label, confidence=confidence, explanation="")


def routed(
    *,
    rules_: RulesVerdict = CLEAN_RULES,
    omni: ModerationResult | Unavailable = CLEAN_OMNI,
    policy: PolicyVerdict | Unavailable | None = OK,
    **flags: bool,
) -> Routing:
    return route(Checks(rules=rules_, omni=omni, policy=policy, **flags))


def test_clean_content_is_published() -> None:
    assert routed() == Routing(route=Route.PUBLISH)
    assert routed(policy=None) == Routing(
        route=Route.PUBLISH
    )  # уровень ≥ 1, классификатор не звали


def test_stop_word_flag_waits_for_a_moderator() -> None:
    result = routed(rules_=rules(RuleCategory.CONTACTS, RuleAction.FLAG, "phone"))

    assert (result.route, result.queue) == (Route.REVIEW, Queue.PREMOD)
    assert result.signals == ("rule:contacts:flag:phone",)


def test_p0_rule_blocks() -> None:
    result = routed(rules_=rules(RuleCategory.DRUGS, RuleAction.BLOCK, "закладчик*"))

    assert (result.route, result.queue, result.reason_code) == (
        Route.BLOCK,
        Queue.SAFETY,
        "drug_courier",
    )


@pytest.mark.parametrize(
    ("checks", "queue", "signal"),
    [
        ({"omni": NO_KEY}, Queue.PREMOD, "omni:unavailable:no_key"),  # AI недоступен — к человеку
        ({"policy": NO_KEY}, Queue.PREMOD, "classifier:unavailable:no_key"),
        (
            {"omni": ModerationResult(flagged=True, scores={"violence": 0.9, "hate": 0.2})},
            Queue.PREMOD,
            "omni:violence",
        ),
        (
            {"policy": verdict(PolicyLabel.PREPAYMENT_SCAM)},
            Queue.FRAUD,
            "classifier:prepayment_scam:0.95",
        ),
        (
            {"policy": verdict(PolicyLabel.DRUG_COURIER, 0.7)},
            Queue.SAFETY,
            "classifier:drug_courier:0.70",
        ),
        ({"policy": verdict(PolicyLabel.OK, 0.6)}, Queue.PREMOD, "classifier:unsure:0.60"),
        ({"always_review": True}, Queue.PREMOD, "always_review"),  # профили новых
        ({"risky_category": True}, Queue.PREMOD, "risky_category"),
    ],
)
def test_every_doubt_goes_to_a_queue(checks: dict[str, object], queue: Queue, signal: str) -> None:
    result = routed(**checks)  # type: ignore[arg-type]

    assert (result.route, result.queue, result.signals) == (Route.REVIEW, queue, (signal,))


@pytest.mark.parametrize(
    ("checks", "flagged"),
    [
        ({"rules_": rules(RuleCategory.SPAM, RuleAction.FLAG)}, True),
        ({"omni": ModerationResult(flagged=True, scores={"hate": 0.9})}, True),
        ({"policy": verdict(PolicyLabel.SPAM_AD, 0.6)}, True),
        ({"omni": NO_KEY}, False),
        ({"policy": verdict(PolicyLabel.OK, 0.6)}, False),
        ({"policy": verdict(PolicyLabel.CONTACT_LEAK)}, False),
        ({"rules_": rules(RuleCategory.CONTACTS, RuleAction.FLAG)}, False),
        (
            {
                "rules_": RulesVerdict(
                    (
                        RuleMatch(
                            source=MatchSource.DETECTOR,
                            category=RuleCategory.SCAM,
                            action=RuleAction.FLAG,
                            evidence="prepayment",
                        ),
                    )
                )
            },
            False,
        ),
    ],
)
def test_only_a_violation_hides_visible_content(checks: dict[str, object], flagged: bool) -> None:
    """Сообщение чата уже видно: прячет его признак нарушения, а не сомнение или детектор."""
    result = routed(**checks)  # type: ignore[arg-type]

    assert (result.route, result.flagged) == (Route.REVIEW, flagged)


def test_strictest_signal_picks_the_queue() -> None:
    result = routed(
        rules_=rules(RuleCategory.SPAM, RuleAction.FLAG),
        policy=verdict(PolicyLabel.MULE_RECRUITMENT),
        always_review=True,
    )

    assert result.queue is Queue.FRAUD
    assert len(result.signals) == 3


def test_sampled_publication_is_checked_afterwards() -> None:
    result = routed(sampled=True)

    assert result == Routing(
        route=Route.PUBLISH, queue=Queue.PREMOD, signals=("sample",), post_review=True
    )
    assert routed(sampled=True, always_review=True).route is Route.REVIEW


def test_classifier_is_called_for_level_zero_and_any_flag() -> None:
    assert needs_classifier(trust_level=0, rules=CLEAN_RULES, omni=CLEAN_OMNI)
    assert not needs_classifier(trust_level=1, rules=CLEAN_RULES, omni=CLEAN_OMNI)
    assert needs_classifier(trust_level=2, rules=CLEAN_RULES, omni=ModerationResult(flagged=True))
    assert needs_classifier(
        trust_level=2, rules=rules(RuleCategory.SPAM, RuleAction.FLAG), omni=CLEAN_OMNI
    )


def test_sample_is_stable_and_follows_the_rate() -> None:
    ids = [UUID(int=n * 7919) for n in range(1, 2001)]

    share = sum(sampled(entity_id, 0.1) for entity_id in ids) / len(ids)

    assert 0.07 < share < 0.13
    assert [sampled(i, 0.1) for i in ids[:50]] == [sampled(i, 0.1) for i in ids[:50]]
    assert not any(sampled(i, 0.0) for i in ids)
    assert all(sampled(i, 1.0) for i in ids)
