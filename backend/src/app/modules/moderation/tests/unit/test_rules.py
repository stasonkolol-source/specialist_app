"""Контент-правила (DEVELOPMENT_PLAN 2.4): слова с обфускацией, регулярки по скелету, домены,
детекторы platform/text и вердикт по строгости. Словарь репозитория и набор примеров
проверяет tests/unit/test_seeds.py."""

import time

import pytest

from app.modules.moderation.domain.rules import (
    MAX_PATTERN,
    ContentRule,
    InvalidRuleError,
    MatchSource,
    RuleAction,
    RuleCategory,
    RuleKind,
    RuleSet,
    compile_rule,
    nested_quantifier,
)

pytestmark = pytest.mark.unit

FLAG, SHADOW, BLOCK = RuleAction.FLAG, RuleAction.SHADOW, RuleAction.BLOCK
WORD, REGEX, DOMAIN = RuleKind.WORD, RuleKind.REGEX, RuleKind.DOMAIN


def rule(
    pattern: str,
    kind: RuleKind = WORD,
    action: RuleAction = FLAG,
    category: RuleCategory = RuleCategory.DRUGS,
    *,
    active: bool = True,
    rule_id: int | None = None,
) -> ContentRule:
    return ContentRule(
        pattern=pattern, kind=kind, action=action, category=category, active=active, id=rule_id
    )


def evidence(rules: RuleSet, text: str) -> list[str]:
    return [m.evidence for m in rules.check(text).matches]


@pytest.mark.parametrize(
    "text",
    [
        "Ищем закладчика",
        "ищем ЗАКЛАДЧИКОВ",
        "Tražimo zakladčika",  # латиницей с диакритикой
        "з.а.к.л.а.д.ч.и.к нужен",
        "закладчиииик",
        "3акладчик",  # цифра вместо буквы
    ],
)
def test_word_with_star_survives_disguises(text: str) -> None:
    assert evidence(RuleSet([rule("закладчик*", action=BLOCK)]), text) == ["закладчик*"]


@pytest.mark.parametrize("text", ["надзакладчик", "закладка фундамента", "zakladi"])
def test_word_does_not_match_inside_other_words(text: str) -> None:
    assert evidence(RuleSet([rule("закладчик*")]), text) == []


def test_word_without_star_is_the_whole_word() -> None:
    rules = RuleSet([rule("droga"), rule("drogu")])

    assert evidence(rules, "Prodajem drogu") == ["drogu"]
    assert evidence(rules, "Kupila sam boju u drogeriji") == []


def test_phrase_matches_words_in_a_row_in_any_script() -> None:
    rules = RuleSet([rule("масажа са срећним крајем", category=RuleCategory.ESCORT)])

    assert evidence(rules, "Masaža sa srećnim krajem!") == ["масажа са срећним крајем"]
    assert evidence(rules, "Masaža, sa srećnim krajem") == ["масажа са срећним крајем"]
    assert evidence(rules, "Masaža i srećan kraj") == []


def test_regex_works_on_the_skeleton() -> None:
    rules = RuleSet([rule(r"\bzarabot\w* (?:ot|do) \d+", REGEX, category=RuleCategory.SPAM)])

    assert rules.check("Заработок ОТ 3000 в день").action is FLAG
    assert rules.check("Zarabotak do 100 evra").action is FLAG
    assert rules.check("Заработок хороший").action is None


def test_regex_may_start_with_word_boundary_before_a_letter() -> None:
    assert compile_rule(rule(r"\bbanka\b", REGEX)) is not None


@pytest.mark.parametrize(
    "pattern",
    [r"\bzarabot\w* (?:ot|do) \d+", r"(?:ab)+", r"[(+)]+", r"(a|b)+", r"\(a+\)+", r"(ab)?+"],
)
def test_single_level_repetition_is_fine(pattern: str) -> None:
    assert not nested_quantifier(pattern)


@pytest.mark.parametrize(
    ("text", "hit"),
    [
        ("Plati ovde: https://bit.ly/3xYz", True),
        ("link: go.bit.ly/abc", True),
        ("bit [.] ly/abc", True),
        ("notbit.ly/abc", False),
        ("Moj sajt example.rs", False),
    ],
)
def test_domain_matches_links_and_subdomains(text: str, hit: bool) -> None:
    rules = RuleSet([rule("bit.ly", DOMAIN, category=RuleCategory.SPAM)])

    assert ("bit.ly" in evidence(rules, text)) is hit


def test_invisible_characters_accents_and_lookalikes_do_not_hide_a_word() -> None:
    rules = RuleSet([rule("закладчик*", action=BLOCK), rule("kokain*")])

    assert rules.check("Ищем закла\u200bдчиков").action is BLOCK  # zero-width
    assert rules.check("Ищем закла\u00adдчиков").action is BLOCK  # мягкий перенос
    assert rules.check("Нужны закладчи\u0301ки").action is BLOCK  # ударение
    assert rules.check("Ishchem zakladchikov").action is BLOCK  # русский транслит
    assert evidence(rules, "Prodajem k\u03bfkain") == ["kokain*"]  # греческая «ο»


def test_detectors_work_without_any_rule() -> None:
    verdict = RuleSet().check("Nudim avans 50%, zovi +381 64 123 4567 ili piši na @ivan_ns")

    assert verdict.action is FLAG
    assert verdict.categories == {RuleCategory.CONTACTS, RuleCategory.SCAM}
    assert {m.source for m in verdict.matches} == {MatchSource.DETECTOR}
    assert [m.evidence for m in verdict.matches] == ["phone, username", "prepayment"]


@pytest.mark.parametrize(
    "text",
    [
        "a" + " " * 19_993 + "@b.com",
        "a@" + " " * 19_990 + "b.com",
        "t" + " " * 19_990 + ". me/x",
        "x [.] " * 3_000,
    ],
    ids=["before-at", "after-at", "before-dot", "hidden-dots"],
)
def test_check_is_linear_on_long_whitespace(text: str) -> None:
    rules = RuleSet([rule("bit.ly", DOMAIN, category=RuleCategory.SPAM), rule("kokain*")])
    started = time.perf_counter()
    rules.check(text)
    RuleSet().check(text)
    assert time.perf_counter() - started < 3.0  # линейно — сотые доли секунды


def test_regex_runs_on_re2_in_linear_time() -> None:
    # вложенных групп нет — эвристика не ловит, а `re` перебирал бы это полиномом пятой степени
    rules = RuleSet([rule(r"\w*\w*\w*\w*\w*x", REGEX, category=RuleCategory.SPAM)])
    started = time.perf_counter()

    assert rules.check("ab" * 9_999).action is None
    assert time.perf_counter() - started < 1.0  # RE2: доли миллисекунды
    assert rules.check("abx").action is FLAG


def test_regex_error_explains_what_re2_does_not_support() -> None:
    with pytest.raises(InvalidRuleError, match=r"\(RE2\): invalid perl operator: \(\?<"):
        compile_rule(rule(r"(?<=ne )kupim", REGEX))


def test_verdict_takes_the_strictest_action_and_keeps_every_match() -> None:
    rules = RuleSet(
        [
            rule("kokain*", rule_id=1),
            rule("kladmen*", action=BLOCK, rule_id=2),
            rule("spam farma", action=SHADOW, category=RuleCategory.SPAM, rule_id=3),
        ]
    )

    verdict = rules.check("Kokain, kladmeni i spam farma")

    assert verdict.action is BLOCK
    assert [m.rule_id for m in verdict.matches] == [1, 2, 3]
    assert verdict.categories == {RuleCategory.DRUGS, RuleCategory.SPAM}
    assert rules.check("Sve je u redu").action is None


def test_inactive_rules_are_skipped_and_broken_ones_do_not_stop_the_rest() -> None:
    rules = RuleSet(
        [
            rule("kokain*", active=False),
            rule("(unclosed", REGEX, rule_id=7),
            rule("heroin*"),
        ]
    )

    assert evidence(rules, "kokain i heroin") == ["heroin*"]
    assert len(rules) == 1
    [(broken, reason)] = rules.rejected
    assert broken.id == 7
    assert "does not compile" in reason


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        (rule("pro*"), "at least 4"),
        (rule("za*kladchik"), "only at the end"),
        (rule("•••"), "no letters"),
        (rule(" "), "1–200"),
        (rule("x" * (MAX_PATTERN + 1)), "1–200"),
        (rule("x*", REGEX), "empty text"),
        (rule(r"\b", REGEX), "empty text"),  # на пустом тексте молчит, но совпал бы везде
        (rule(r"kupim|\b", REGEX), "empty text"),
        (rule("(unclosed", REGEX), "does not compile"),
        (rule("a{1001}", REGEX), "does not compile"),  # предел повтора RE2 — 1000
        (rule(r"(?<!ne )kupim", REGEX), "does not compile"),  # lookbehind в RE2 нет
        (rule(r"(da) \1", REGEX), "does not compile"),  # обратных ссылок тоже
        (rule(r"(\w+\s?)+kupim", REGEX), "nested quantifiers"),
        (rule(r"(\d+)+ din", REGEX), "nested quantifiers"),
        (rule(r"((a+)b)+", REGEX), "nested quantifiers"),
        (rule("massage", REGEX), "double letters"),
        (rule("Bit.ly", DOMAIN), "lower case"),
        (rule("https://bit.ly", DOMAIN), "example.com"),
        (rule("localhost", DOMAIN), "example.com"),
    ],
)
def test_bad_rules_are_rejected(bad: ContentRule, reason: str) -> None:
    with pytest.raises(InvalidRuleError, match=reason):
        compile_rule(bad)
