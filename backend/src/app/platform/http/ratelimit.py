"""Лимиты в HTTP (ARCHITECTURE §8.1, §13.3): зависимость роутера и заголовки RateLimit-*.

    @router.get("/search", dependencies=[Depends(RateLimit(SEARCH_GUEST))])

Состояние окна сохраняется в request.state: middleware добавляет `RateLimit-Limit`,
`RateLimit-Remaining`, `RateLimit-Reset` в успешный ответ, включая готовый Response;
превышение — RateLimitedError, его отображает interfaces/http/errors.py (429 + Retry-After).
"""

from collections.abc import Callable

from fastapi import Request

from app.platform.http.security import optional_principal
from app.platform.kernel.principal import Principal
from app.platform.ratelimit import Rate, RateLimiter, RateStatus, user_subject

UNKNOWN_IP = "unknown"


def client_ip(request: Request) -> str:
    """Адрес клиента. За kamal-proxy его подставляет uvicorn из X-Forwarded-For."""
    return f"ip:{request.client.host if request.client else UNKNOWN_IP}"


def user_or_ip(request: Request) -> str:
    """Вошедший — по пользователю, гость — по адресу."""
    principal = getattr(request.state, "principal", None)
    if isinstance(principal, Principal):
        return user_subject(principal.user_id)
    return client_ip(request)


def rate_limit_headers(status: RateStatus) -> dict[str, str]:
    return {
        "RateLimit-Limit": str(status.limit),
        "RateLimit-Remaining": str(status.remaining),
        "RateLimit-Reset": str(status.reset_after),
    }


class RateLimit:
    """Зависимость FastAPI: засчитать запрос в лимит `rate` по субъекту из `key`."""

    def __init__(self, rate: Rate, *, key: Callable[[Request], str] = user_or_ip) -> None:
        self.rate = rate
        self.key = key

    async def __call__(self, request: Request) -> None:
        limiter = await request.state.dishka_container.get(RateLimiter)
        status = await limiter.hit(self.rate, self.key(request))
        request.state.rate_limit = status


class GuestOrUserRateLimit:
    """Лимит открытого эндпоинта: гость — по адресу в `guest`, вошедший — по пользователю в
    `user` (ARCHITECTURE §13.3: поиск и каталог — 60 / 120 в минуту)."""

    def __init__(self, *, guest: Rate, user: Rate) -> None:
        self.guest, self.user = guest, user

    async def __call__(self, request: Request) -> None:
        principal = await optional_principal(request)
        if principal is None:
            rate, subject = self.guest, client_ip(request)
        else:
            rate, subject = self.user, user_subject(principal.user_id)
        limiter = await request.state.dishka_container.get(RateLimiter)
        status = await limiter.hit(rate, subject)
        request.state.rate_limit = status
