"""Ошибки модуля growth со стабильными code (ADR-0020 §9)."""

from app.platform.kernel.errors import DomainValidationError


class InvalidStartLinkError(DomainValidationError):
    """Ссылку не закодировать в startapp (ARCHITECTURE §11.4).

    `reason`: `shape` — поля не соответствуют типу, `ref` — в коде реферала не только
    `[A-Za-z0-9]`, `length` — код длиннее 64 символов.
    """

    code = "invalid_start_link"
