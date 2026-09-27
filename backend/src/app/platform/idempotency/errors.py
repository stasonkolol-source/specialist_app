"""Ошибки идемпотентности (ADR-0020 §4)."""

from app.platform.kernel.errors import ConflictError, DomainValidationError


class IdempotencyKeyRequiredError(DomainValidationError):
    code = "idempotency_key_required"


class InvalidIdempotencyKeyError(DomainValidationError):
    code = "invalid_idempotency_key"


class IdempotencyKeyReusedError(DomainValidationError):
    """Тот же ключ с другим телом запроса: клиент перепутал ключи."""

    code = "idempotency_key_reused"


class IdempotencyInProgressError(ConflictError):
    """Первый запрос с этим ключом ещё выполняется."""

    code = "idempotency_in_progress"
