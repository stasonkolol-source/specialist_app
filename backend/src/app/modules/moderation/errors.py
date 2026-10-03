"""Ошибки модуля moderation со стабильными code (ADR-0020 §9)."""

from app.platform.kernel.errors import (
    ConcurrentModificationError,
    ConflictError,
    DomainValidationError,
    NotFoundError,
)


class CaseNotFoundError(NotFoundError):
    code = "case_not_found"


class CaseAlreadyOpenError(ConcurrentModificationError):
    """Параллельный запрос только что открыл кейс того же объекта: команда повторяется и
    дописывает повод в открытый кейс."""

    code = "case_already_open"


class CaseStateError(ConflictError):
    """Действие недоступно в текущем статусе кейса: решённый кейс не решают снова."""

    code = "case_state_conflict"


class CaseTakenError(ConflictError):
    """Кейс уже разбирает другой модератор."""

    code = "case_taken"


class InvalidDecisionError(DomainValidationError):
    """Решение без машинного кода причины или с неверным кодом."""

    code = "invalid_decision"


class CaseKindError(ConflictError):
    """Кейс такого вида так не решить: спор по сделке (`dispute`) решается с исходом сделки —
    `cli dispute-resolve`, а не `moderation-decide`."""

    code = "case_kind_conflict"
    public_params = ("entity_type",)
