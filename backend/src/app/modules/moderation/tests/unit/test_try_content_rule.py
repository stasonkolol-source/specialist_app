"""Проба правила в админке (DEVELOPMENT_PLAN 2.7b): та же проверка, что у сида в seeds-validate,
проба на тексте сотрудника и прогон по набору примеров — у каких примеров поменяется вердикт."""

from dataclasses import dataclass

import pytest

from app.modules.moderation.application.use_cases.try_content_rule import (
    TryContentRule,
    TryContentRuleCommand,
)
from app.modules.moderation.domain.rules import (
    ContentRule,
    MatchSource,
    RuleAction,
    RuleCategory,
    RuleExample,
    RuleKind,
)
from app.modules.moderation.infrastructure.regex import RE2
from app.modules.moderation.infrastructure.rule_examples import YamlRuleExamples
from app.modules.moderation.tests.fakes import FakeRuleSource

pytestmark = pytest.mark.unit

SPAM, FLAG = RuleCategory.SPAM, RuleAction.FLAG
ZARADA = ContentRule(id=7, pattern="brza zarada", kind=RuleKind.WORD, action=FLAG, category=SPAM)
EXAMPLES = (
    RuleExample(text="Prodajem bicikl, malo vožen", action=None),
    RuleExample(text="Brza zarada od kuće", action=FLAG, categories=frozenset({SPAM})),
)


@dataclass
class StaticExamples:
    examples: tuple[RuleExample, ...] = EXAMPLES

    def load(self) -> tuple[RuleExample, ...]:
        return self.examples


def regex(pattern: str, rule_id: int | None = None) -> ContentRule:
    return ContentRule(id=rule_id, pattern=pattern, kind=RuleKind.REGEX, action=FLAG, category=SPAM)


async def test_rule_that_seeds_validate_rejects_is_not_tried() -> None:
    trial = await TryContentRule(FakeRuleSource([ZARADA]), StaticExamples(), RE2)(
        TryContentRuleCommand(rule=regex(r"(?<!ne )kupim"), sample="kupim")
    )

    assert trial.error is not None
    assert "does not compile (RE2)" in trial.error
    assert (trial.changes, trial.examples, trial.matches) == ((), 0, ())


async def test_new_rule_shows_examples_whose_verdict_changes() -> None:
    trial = await TryContentRule(FakeRuleSource([ZARADA]), StaticExamples(), RE2)(
        TryContentRuleCommand(rule=regex(r"\bbicikl\w*"))
    )

    assert trial.error is None
    assert trial.examples == 2
    [change] = trial.changes
    assert change.text == "Prodajem bicikl, malo vožen"
    assert (change.expected, change.before, change.after) == ("pass []", "pass []", "flag ['spam']")


async def test_edited_rule_replaces_its_previous_version() -> None:
    use_case = TryContentRule(FakeRuleSource([ZARADA]), StaticExamples(), RE2)

    same = await use_case(TryContentRuleCommand(rule=regex(r"\bbrz\w* zarad\w*", rule_id=7)))
    lost = await use_case(TryContentRuleCommand(rule=regex(r"\bspora zarada", rule_id=7)))

    assert same.changes == ()
    [change] = lost.changes
    assert (change.text, change.before, change.after) == (
        "Brza zarada od kuće",
        "flag ['spam']",
        "pass []",
    )
    assert change.expected == "flag ['spam']"  # правка разойдётся с набором — видно до записи


async def test_sample_text_shows_skeleton_and_what_fired() -> None:
    trial = await TryContentRule(FakeRuleSource([ZARADA]), StaticExamples(), RE2)(
        TryContentRuleCommand(
            rule=regex(r"\bzarabot\w* (?:ot|do) \d+"), sample="Заработок ОТ 3000!"
        )
    )

    assert trial.skeleton == "zarabotok ot 3000"
    assert trial.hit is True
    assert [(m.source, m.evidence) for m in trial.matches] == [
        (MatchSource.RULE, r"\bzarabot\w* (?:ot|do) \d+")
    ]


def test_repository_examples_load_for_the_admin() -> None:
    examples = YamlRuleExamples().load()

    assert len(examples) >= 90
    assert any(e.action is None for e in examples)  # «pass» — правила молчат
    assert YamlRuleExamples().load() == examples
