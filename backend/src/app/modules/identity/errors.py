"""Ошибки модуля identity со стабильными code (ADR-0020 §9)."""

from collections.abc import Sequence

from app.platform.kernel.errors import (
    ConcurrentModificationError,
    ConflictError,
    DomainValidationError,
    ExternalServiceError,
    ForbiddenError,
    NotFoundError,
)


class UserNotFoundError(NotFoundError):
    code = "user_not_found"


class SessionNotFoundError(NotFoundError):
    code = "session_not_found"


class AccountDeletedError(ForbiddenError):
    """Аккаунт удалён: войти в него нельзя (ZZPL — удаление по запросу, шаг 6.x)."""

    code = "account_deleted"


class UserAlreadyDeletedError(ConflictError):
    code = "user_already_deleted"


class ConcurrentLoginError(ConcurrentModificationError):
    """Два первых входа одного Telegram-аккаунта одновременно: второй повторяет запрос."""

    code = "concurrent_login"


class InvalidDisplayNameError(DomainValidationError):
    """Имя пустое после очистки от пробелов и невидимых символов."""

    code = "invalid_display_name"


class ConsentRequiredError(ForbiddenError):
    """Создающее действие до принятия правил площадки и политики (S02c).

    `documents` — чего не хватает (`terms`, `privacy`, `age_18`), поле ответа: клиент
    показывает галочку с действующими версиями из client-config.
    """

    code = "consent_required"
    public_params = ("documents",)

    def __init__(self, *, documents: Sequence[str]) -> None:
        super().__init__(documents=list(documents))
        self.documents = tuple(documents)


class LegalVersionOutdatedError(ConflictError):
    """Клиент принимает не ту версию документа, что действует сейчас.

    `document` (`terms`, `privacy`) и `current` — действующая версия, поля ответа: клиент
    показывает текст этой версии и просит галочку заново, не полагаясь на client-config
    из кэша WebView (он может быть старше минуты).
    """

    code = "legal_version_outdated"
    public_params = ("document", "current")

    def __init__(self, *, document: str, current: str) -> None:
        super().__init__(document=document, current=current)
        self.document = document
        self.current = current


class LegalVersionsUnavailableError(ExternalServiceError):
    """В client-config нет действующих версий правил или политики: согласие не записать."""

    code = "legal_versions_unavailable"


class UnknownCityError(DomainValidationError):
    """Города нет в справочнике geo."""

    code = "unknown_city"


class CityNotAvailableError(DomainValidationError):
    """Город в справочнике со статусом «скоро»: выбрать его ещё нельзя."""

    code = "city_not_available"


class InvalidRestrictionError(DomainValidationError):
    """Санкция без машинного кода причины или с концом в прошлом."""

    code = "invalid_restriction"
