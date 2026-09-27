"""Ошибки входа: все — 401 (NotAuthenticatedError), `code` говорит клиенту, что делать.

- `init_data_expired` — открыть Mini App заново (нужен свежий initData);
- `token_expired` — обновить access через refresh;
- остальное — начать вход заново.
"""

from app.platform.kernel.errors import NotAuthenticatedError


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
