"""Движок регулярок контент-правил — RE2 (google-re2) за портом `RegexEngine` домена (2.7b).

RE2 ищет за время, линейное от длины текста, при любом шаблоне: в его синтаксисе нет lookaround и
обратных ссылок, поэтому нет и перебора, которым неудачный шаблон повесил бы стандартный `re`, —
регулярки заводит и админка. Один движок на процесс: собранные шаблоны google-re2 кэширует сам
(LRU на 128), снимок правил раз в TTL их не пересобирает.
"""

import re2

from app.modules.moderation.domain.rules import InvalidRuleError, Matcher

_OPTIONS = re2.Options()
_OPTIONS.case_sensitive = False
_OPTIONS.never_capture = True  # нужен только факт совпадения: без групп RE2 обходится проходом DFA
_OPTIONS.log_errors = False  # ошибку шаблона показывает InvalidRuleError, а не stderr процесса


class Re2Engine:
    def compile(self, pattern: str) -> Matcher:
        try:
            regex: Matcher = re2.compile(pattern, _OPTIONS)
        except (re2.error, ValueError) as exc:  # ValueError — суррогат, которого нет в UTF-8
            raise InvalidRuleError(f"regex does not compile (RE2): {_reason(exc)}") from exc
        return regex


def _reason(exc: Exception) -> str:
    """Текст ошибки RE2 приходит байтами: «missing ): (unclosed»."""
    reason = exc.args[0] if exc.args else exc
    return reason.decode(errors="replace") if isinstance(reason, bytes) else str(reason)


RE2 = Re2Engine()
"""Движок для мест без DI: `cli seeds-validate`, снимок правил по умолчанию, тесты."""
