"""Ошибки кодека deep links (ARCHITECTURE §11.4)."""

from app.platform.kernel.errors import DomainValidationError


class InvalidStartLinkError(DomainValidationError):
    """Ссылку не закодировать в startapp.

    `reason`: `shape` — поля не соответствуют типу, `ref` — в коде реферала не только
    `[A-Za-z0-9]`, `length` — код длиннее 64 символов.
    """

    code = "invalid_start_link"
