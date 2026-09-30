"""Жёсткие правила — первый шаг конвейера модерации (ARCHITECTURE §14.1, DEVELOPMENT_PLAN 2.4).

Словарь из БД (стоп-слова, регулярки, домены), детекторы контактов и предоплаты из
platform/text и velocity. Конвейер (2.5a) решает по вердикту: block — P0, flag — дальше в
omni-moderation и классификатор, ничего — дальше по обычному пути.

Проверка учитывает текст в счётчиках velocity: повторная проверка той же единицы контента
(повтор задачи, правка без изменения текста) их не увеличивает.
"""

from app.modules.moderation.application.dto import ContentCheck
from app.modules.moderation.application.ports import RuleSource, VelocityCounter
from app.modules.moderation.domain.rules import MatchSource, RuleMatch, RulesVerdict
from app.modules.moderation.domain.velocity import VELOCITY_LIMITS, VelocityScope, fingerprint


class ContentRulesChecker:
    def __init__(self, rules: RuleSource, velocity: VelocityCounter) -> None:
        self._rules, self._velocity = rules, velocity

    async def check(self, content: ContentCheck) -> RulesVerdict:
        verdict = (await self._rules.current()).check(content.text)
        return verdict.extended(await self._velocity_matches(content))

    async def _velocity_matches(self, content: ContentCheck) -> list[RuleMatch]:
        digest = fingerprint(content.text)
        if digest is None:
            return []
        matches: list[RuleMatch] = []
        for limit in VELOCITY_LIMITS:
            if content.kind not in limit.kinds:
                continue
            if limit.scope is VelocityScope.ACCOUNTS:
                key, member = f"{limit.name}:{digest}", str(content.author_id)
            else:
                key, member = f"{limit.name}:{content.author_id}:{digest}", str(content.content_id)
            count = await self._velocity.add(key, member, window=limit.window)
            if count is not None and count >= limit.threshold:
                matches.append(
                    RuleMatch(
                        source=MatchSource.VELOCITY,
                        category=limit.category,
                        action=limit.action,
                        evidence=f"{limit.name}: {count}",
                    )
                )
        return matches
