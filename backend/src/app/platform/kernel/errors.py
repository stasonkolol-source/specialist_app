"""Базовые ошибки (ADR-0020 §9). Про HTTP, бот и задачи ничего не знают.

Конкретная ошибка — класс в `errors.py` модуля с уникальным `code` в snake_case и
именованными параметрами. Отображение в ответ (RFC 9457), сообщение бота и поведение
задачи определяется базовым классом в одном месте на интерфейс.
"""

from typing import ClassVar


class DomainError(Exception):
    """Ожидаемая ошибка предметной области со стабильным машинным кодом."""

    code: ClassVar[str] = "domain_error"

    def __init__(self, **params: object) -> None:
        self.params: dict[str, object] = params
        details = ", ".join(f"{k}={v!r}" for k, v in params.items())
        super().__init__(f"{self.code}({details})" if details else self.code)


class NotFoundError(DomainError):
    """404: объекта нет или он не виден текущему пользователю."""

    code = "not_found"


class NotAuthenticatedError(DomainError):
    """401: нет действующей сессии (или её отозвали)."""

    code = "not_authenticated"


class ForbiddenError(DomainError):
    """403: у пользователя нет прав на действие."""

    code = "forbidden"


class RestrictedError(ForbiddenError):
    """403 `restricted`: действие запрещено санкцией (identity.restrictions)."""

    code = "restricted"


class ConflictError(DomainError):
    """409: действие невозможно в текущем состоянии (запрещённый переход, лимит)."""

    code = "conflict"


class ConcurrentModificationError(ConflictError):
    """409: строку параллельно изменили (StaleDataError ORM). В задаче — повтор."""

    code = "concurrent_modification"


class StaleVersionError(DomainError):
    """412: версия из If-Match не совпала с текущей."""

    code = "stale_version"

    def __init__(self, *, expected: int, actual: int) -> None:
        super().__init__(expected=expected, actual=actual)
        self.expected = expected
        self.actual = actual


class DomainValidationError(DomainError):
    """422: значение нарушает правило предметной области."""

    code = "validation_failed"


class RateLimitedError(DomainError):
    """429: слишком часто. `retry_after` — секунды."""

    code = "rate_limited"

    def __init__(self, *, retry_after: int, **params: object) -> None:
        super().__init__(retry_after=retry_after, **params)
        self.retry_after = retry_after


class ExternalServiceError(DomainError):
    """503: внешний сервис недоступен или вернул 5xx. В задаче — повтор с бэкоффом."""

    code = "external_service_unavailable"


class ProgrammingError(RuntimeError):
    """Ошибка программиста (забытый save, вложенная транзакция). 500, Sentry, алерт."""
