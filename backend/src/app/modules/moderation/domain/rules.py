"""Контент-правила — первый, самый дешёвый шаг конвейера модерации (ARCHITECTURE §14.1,
ADR-0016 §3, DEVELOPMENT_PLAN 2.4).

Правило — строка `moderation.content_rules`:
- `word` — слово или фраза словаря (стоп-слова ru, sr обеими письменностями, uk, en).
  Сравнение по скелету (platform/text/normalize.py): «пред0плата», «п.р.е.д.о.п.л.а.т.а»,
  «predoplata» и «ПРЕДОПЛАААТА» — одно слово. `*` в конце — любое окончание («закладчик*»:
  «закладчика», «закладчики»), иначе слово целиком; фраза — слова подряд.
- `regex` — регулярное выражение по скелету: латиница ASCII в нижнем регистре, слова через
  пробел, без двойных букв. Для шаблонов, которые не выразить словами.
- `domain` — домен ссылки или почты: `bit.ly` ловит `https://bit.ly/x`, `sub.bit.ly` и
  «bit [.] ly».

Кроме правил из БД всегда работают детекторы platform/text: контакты (категория contacts) и
просьба о предоплате (scam), оба — flag. Контакты в переписке до договорённости скрывает
сама переписка (6.3a), здесь это сигнал для модерации.

Действия по строгости: flag — в LLM-классификатор и при сомнении в очередь P2; shadow —
тихий карантин, только для ботов и спам-ферм (research/06 §2.3, DSA recital 55); block — P0:
скрыть, заморозить аккаунт, кейс. Вердикт — самое строгое из сработавшего.

`lang` — язык словаря, для сопровождения: правило применяется к любому тексту — язык текста
заранее не известен, а скелет сводит письменности к одной.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from app.platform.text.contact_masking import find_prepayment, scan_contacts
from app.platform.text.normalize import skeleton


class RuleKind(StrEnum):
    WORD = "word"
    REGEX = "regex"
    DOMAIN = "domain"


class RuleAction(StrEnum):
    FLAG = "flag"
    SHADOW = "shadow"
    BLOCK = "block"


SEVERITY = {RuleAction.FLAG: 1, RuleAction.SHADOW: 2, RuleAction.BLOCK: 3}


class RuleCategory(StrEnum):
    """Что нарушено; близко к меткам классификатора ADR-0016."""

    DRUGS = "drugs"
    WEAPONS = "weapons"
    ESCORT = "escort"
    SCAM = "scam"
    MULE = "mule"
    CONTACTS = "contacts"
    SPAM = "spam"
    VACANCY = "vacancy"


class RuleLanguage(StrEnum):
    RU = "ru"
    SR = "sr"
    UK = "uk"
    EN = "en"


class MatchSource(StrEnum):
    RULE = "rule"
    DETECTOR = "detector"
    VELOCITY = "velocity"


MAX_PATTERN = 200
MIN_STEM = 4
"""`*` после основы короче — ловит слишком много слов («pro*»)."""
MAX_TEXT = 20_000
"""Дальше текст не смотрим: тексты продукта короче, это защита от мусора."""
_DOMAIN = re.compile(r"^[^\W_](?:[\w\-]*[^\W_])?(?:\.[^\W_](?:[\w\-]*[^\W_])?)+$")
_DOUBLE_LETTER = re.compile(r"([a-z])\1", re.IGNORECASE)
_ESCAPE = re.compile(r"\\.")
"""`\bb…` — это \b и b, а не двойная b."""


class InvalidRuleError(ValueError):
    """Правило не компилируется: ошибка словаря, а не пользователя."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ContentRule:
    pattern: str
    kind: RuleKind
    action: RuleAction
    category: RuleCategory
    lang: RuleLanguage | None = None
    active: bool = True
    id: int | None = None
    """None — правило из сида до записи в БД."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RuleMatch:
    source: MatchSource
    category: RuleCategory
    action: RuleAction
    evidence: str
    """Что сработало, для модератора: слово или домен словаря, вид контакта, velocity-правило."""
    rule_id: int | None = None


@dataclass(frozen=True, slots=True)
class RulesVerdict:
    matches: tuple[RuleMatch, ...] = ()

    @property
    def action(self) -> RuleAction | None:
        """Самое строгое действие; None — правила ничего не нашли."""
        return max((m.action for m in self.matches), key=SEVERITY.__getitem__, default=None)

    @property
    def categories(self) -> frozenset[RuleCategory]:
        return frozenset(m.category for m in self.matches)

    def extended(self, matches: Iterable[RuleMatch]) -> RulesVerdict:
        return RulesVerdict((*self.matches, *matches))


@dataclass(frozen=True, slots=True)
class _Compiled:
    rule: ContentRule
    regex: re.Pattern[str] | None
    """По скелету текста; у domain — None."""


def compile_rule(rule: ContentRule) -> re.Pattern[str] | None:
    """Проверить правило и собрать регулярное выражение по скелету (у domain — None)."""
    pattern = rule.pattern
    if not pattern.strip() or len(pattern) > MAX_PATTERN:
        raise InvalidRuleError(f"pattern must be 1–{MAX_PATTERN} characters")
    match rule.kind:
        case RuleKind.WORD:
            return _word(pattern)
        case RuleKind.REGEX:
            return _regex(pattern)
        case RuleKind.DOMAIN:
            if pattern != pattern.strip().casefold() or not _DOMAIN.match(pattern):
                raise InvalidRuleError("domain must look like example.com, in lower case")
            return None


def _word(pattern: str) -> re.Pattern[str]:
    stem = pattern.removesuffix("*")
    if "*" in stem:
        raise InvalidRuleError("`*` is allowed only at the end of a word rule")
    words = skeleton(stem)
    if not words:
        raise InvalidRuleError("word rule has no letters or digits")
    prefix = stem != pattern
    if prefix and len(words.rsplit(" ", 1)[-1]) < MIN_STEM:
        raise InvalidRuleError(f"stem before `*` must be at least {MIN_STEM} letters")
    ending = r"[a-z0-9]*" if prefix else ""
    return re.compile(rf"(?<![a-z0-9]){re.escape(words)}{ending}(?![a-z0-9])")


def _regex(pattern: str) -> re.Pattern[str]:
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except (re.error, OverflowError, RecursionError, ValueError) as exc:  # «a{4294967296}»
        raise InvalidRuleError(f"regex does not compile: {exc}") from exc
    if regex.search("") is not None:
        raise InvalidRuleError("regex matches an empty text")
    if _DOUBLE_LETTER.search(_ESCAPE.sub(" ", pattern)):
        raise InvalidRuleError("regex works on the skeleton: no double letters (ss → s)")
    return regex


class RuleSet:
    """Действующие правила, собранные для проверки. Правило с ошибкой не роняет остальные:
    оно в `rejected` с причиной (словарь правят люди, опечатка в regex возможна)."""

    def __init__(self, rules: Iterable[ContentRule] = ()) -> None:
        compiled: list[_Compiled] = []
        rejected: list[tuple[ContentRule, str]] = []
        for rule in rules:
            if not rule.active:
                continue
            try:
                compiled.append(_Compiled(rule, compile_rule(rule)))
            except InvalidRuleError as exc:
                rejected.append((rule, str(exc)))
        self._text = tuple(c for c in compiled if c.regex is not None)
        self._domains = tuple(c.rule for c in compiled if c.rule.kind is RuleKind.DOMAIN)
        self.rejected: tuple[tuple[ContentRule, str], ...] = tuple(rejected)

    def __len__(self) -> int:
        return len(self._text) + len(self._domains)

    def check(self, text: str) -> RulesVerdict:
        text = text[:MAX_TEXT]
        words = skeleton(text)
        contacts = scan_contacts(text)
        matches = [
            _matched(c.rule) for c in self._text if c.regex is not None and c.regex.search(words)
        ]
        if self._domains and (hosts := contacts.domains):
            matches.extend(
                _matched(rule)
                for rule in self._domains
                if any(h == rule.pattern or h.endswith("." + rule.pattern) for h in hosts)
            )
        if contacts.findings:
            kinds = ", ".join(dict.fromkeys(f.kind.value for f in contacts.findings))
            matches.append(_detected(RuleCategory.CONTACTS, kinds))
        if find_prepayment(text):
            matches.append(_detected(RuleCategory.SCAM, "prepayment"))
        return RulesVerdict(tuple(matches))


def _matched(rule: ContentRule) -> RuleMatch:
    return RuleMatch(
        source=MatchSource.RULE,
        category=rule.category,
        action=rule.action,
        evidence=rule.pattern,
        rule_id=rule.id,
    )


def _detected(category: RuleCategory, evidence: str) -> RuleMatch:
    return RuleMatch(
        source=MatchSource.DETECTOR, category=category, action=RuleAction.FLAG, evidence=evidence
    )
