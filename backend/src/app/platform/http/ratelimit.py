"""Лимиты в HTTP (ARCHITECTURE §8.1, §13.3): зависимость роутера и заголовки RateLimit-*.

    @router.get("/search", dependencies=[Depends(RateLimit(SEARCH_GUEST))])

Успешный ответ несёт `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset`;
превышение — RateLimitedError, его отображает interfaces/http/errors.py (429 + Retry-After).
"""

from collections.abc import Callable

from fastapi import Request, Response

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

    async def __call__(self, request: Request, response: Response) -> None:
        limiter = await request.state.dishka_container.get(RateLimiter)
        status = await limiter.hit(self.rate, self.key(request))
        response.headers.update(rate_limit_headers(status))
