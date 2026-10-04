"""Ошибки входа: все — 401 (NotAuthenticatedError), `code` говорит клиенту, что делать.

- `init_data_expired` — открыть Mini App заново (нужен свежий initData);
- `token_expired` — обновить access через refresh;
- остальное — начать вход заново.

Отдельно — `csrf_rejected` (403): меняющий запрос к Admin API пришёл не со страницы админки
(platform/http/staff.py).
"""

from app.platform.kernel.errors import ForbiddenError, NotAuthenticatedError


class InvalidInitDataError(NotAuthenticatedError):
    code = "invalid_init_data"


class InitDataExpiredError(NotAuthenticatedError):
    code = "init_data_expired"


class InvalidTokenError(NotAuthenticatedError):
    code = "invalid_token"


class TokenExpiredError(NotAuthenticatedError):
    code = "token_expired"


class SessionRevokedError(NotAuthenticatedError):
    code = "session_revoked"


class InvalidRefreshTokenError(NotAuthenticatedError):
    code = "invalid_refresh_token"


class CsrfRejectedError(ForbiddenError):
    """Меняющий запрос к Admin API без заголовка `X-Requested-With: sosed-admin` или с чужого
    origin (`reason`: header, fetch_site, origin)."""

    code = "csrf_rejected"
