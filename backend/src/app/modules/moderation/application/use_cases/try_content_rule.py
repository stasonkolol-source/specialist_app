"""Проба контент-правила до записи — страница админки «Проверить правило» (DEVELOPMENT_PLAN 2.7b).

- Примут ли правило: та же проверка, что у `cli seeds-validate` и снимка правил (`compile_rule`;
  у регулярки — компиляция RE2, пустое совпадение, двойные буквы, вложенные квантификаторы).
- Что найдёт в тексте сотрудника: скелет текста (регулярку пишут по нему) и вердикт всех правил.
- Прогон по набору seeds/moderation/rule_examples.yaml: у каких примеров поменяется вердикт, если
  правило добавить (при правке — вместо прежней строки), и что ждёт набор.

Ничего не пишет: «до» — действующий снимок правил процесса (админка сбрасывает его после каждой
правки), «после» — тот же снимок с правилом-кандидатом.
"""

from dataclasses import dataclass, replace

from app.modules.moderation.application.ports import RuleExamples, RuleSource
from app.modules.moderation.domain.rules import (
    MAX_TEXT,
    ContentRule,
    InvalidRuleError,
    MatchSource,
    RegexEngine,
    RuleMatch,
    RuleSet,
    compile_rule,
)
from app.platform.text.normalize import skeleton


@dataclass(frozen=True, slots=True, kw_only=True)
class TryContentRuleCommand:
    rule: ContentRule
    """Кандидат; `id` — правимая строка (прежний вариант уходит из «после»), None — новое."""
    sample: str = ""
    """Текст для пробы; пусто — без пробы."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ExampleChange:
    text: str
    expected: str
    """Что ждёт набор, как `RulesVerdict.outcome`: «flag ['drugs']», «pass []»."""
    before: str
    after: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RuleTrial:
    error: str | None = None
    """Почему правило не примут; None — примут."""
    skeleton: str = ""
    """Скелет текста пробы: по нему ищут слова и регулярки."""
    hit: bool = False
    """Кандидат сработал на тексте пробы."""
    matches: tuple[RuleMatch, ...] = ()
    """Вердикт всех правил с кандидатом на тексте пробы (с детекторами platform/text)."""
    changes: tuple[ExampleChange, ...] = ()
    examples: int = 0
    """Сколько примеров набора прогнано."""


class TryContentRule:
    def __init__(self, rules: RuleSource, examples: RuleExamples, engine: RegexEngine) -> None:
        self._rules, self._examples, self._engine = rules, examples, engine

    async def __call__(self, cmd: TryContentRuleCommand) -> RuleTrial:
        candidate = replace(cmd.rule, active=True)
        try:
            compile_rule(candidate, self._engine)
        except InvalidRuleError as exc:
            return RuleTrial(error=str(exc))
        before = await self._rules.current()
        kept = [r for r in before.rules if candidate.id is None or r.id != candidate.id]
        after = RuleSet([*kept, candidate], self._engine)
        changes: list[ExampleChange] = []
        examples = self._examples.load()
        for example in examples:
            was, now = before.check(example.text).outcome, after.check(example.text).outcome
            if was != now:
                changes.append(
                    ExampleChange(
                        text=example.text, expected=example.outcome, before=was, after=now
                    )
                )
        trial = RuleTrial(changes=tuple(changes), examples=len(examples))
        if not cmd.sample.strip():
            return trial
        own = RuleSet([candidate], self._engine).check(cmd.sample).matches
        return replace(
            trial,
            skeleton=skeleton(cmd.sample[:MAX_TEXT]),
            hit=any(match.source is MatchSource.RULE for match in own),
            matches=after.check(cmd.sample).matches,
        )
