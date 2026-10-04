"""Вход персонала в админку (DEVELOPMENT_PLAN 2.7a; ADR-0009, ARCHITECTURE §13.2).

- Логин, пароль и код TOTP проверяет identity (`StaffAuth`): без кода входа нет.
- Неудачные попытки ограничены (Valkey, `limits`): с одного адреса и на один логин; сверх лимита
  — 429 даже с верными данными, пока окно не пройдёт. Удачный вход счётчики не сбрасывает.
- Сессия — подписанная cookie (`SessionMiddleware`, APP_ADMIN_SESSION_KEY) с id сотрудника и
  сроком 8 часов; роли перечитываются на каждый запрос: снятая роль закрывает админку сразу. Та же
  cookie открывает Admin API `/admin/api/v1` (параметры — platform/http/staff.py).
"""

from typing import Final
from uuid import UUID

import structlog
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from app.modules.identity.api import StaffAuth
from app.platform.http.admin import container_of
from app.platform.http.staff import SESSION_COOKIE, SESSION_KEY, SESSION_MAX_AGE
from app.platform.kernel.errors import RateLimitedError
from app.platform.kernel.ids import UserId
from app.platform.ratelimit import Rate, RateLimiter

log = structlog.get_logger(__name__)

LOGIN_FAILURES_IP: Final = Rate("admin.login.ip", "10/15minutes")
LOGIN_FAILURES_ACCOUNT: Final = Rate("admin.login.account", "5/15minutes")


class StaffAuthBackend(AuthenticationBackend):
    def __init__(self, secret_key: str, *, https_only: bool) -> None:
        super().__init__(
            secret_key=secret_key,
            session_cookie=SESSION_COOKIE,
            max_age=SESSION_MAX_AGE,
            same_site="strict",
            https_only=https_only,
        )

    async def login(self, request: Request) -> Response | bool:
        form = await request.form()
        login = str(form.get("username", "")).strip().lower()
        password = str(form.get("password", ""))
        code = str(form.get("otp", ""))
        ip = request.client.host if request.client else "unknown"
        subjects = ((LOGIN_FAILURES_IP, f"ip:{ip}"), (LOGIN_FAILURES_ACCOUNT, f"login:{login}"))
        container = container_of(request)
        limiter = await container.get(RateLimiter)
        for rate, subject in subjects:
            status = await limiter.peek(rate, subject)
            if status.remaining <= 0:
                log.info("staff_login_limited", rate=rate.name)
                return _too_many(status.reset_after)
        member = None
        if login and password and code:
            member = await (await container.get(StaffAuth)).authenticate(
                login, password, code, ip=ip
            )
        if member is None:
            log.info("staff_login_failed")
            for rate, subject in subjects:
                try:
                    await limiter.hit(rate, subject)
                except RateLimitedError as exc:
                    return _too_many(exc.retry_after)
            return False
        request.session.clear()
        request.session[SESSION_KEY] = str(member.user_id)
        return True

    async def logout(self, request: Request) -> Response | bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> Response | bool:
        raw = request.session.get(SESSION_KEY)
        if not isinstance(raw, str):
            return False
        try:
            user_id = UserId(UUID(raw))
        except ValueError:
            request.session.clear()
            return False
        member = await (await container_of(request).get(StaffAuth)).member(user_id)
        if member is None:
            request.session.clear()
            return False
        request.state.staff = member
        return True

    async def get_user_id(self, request: Request) -> str | None:
        staff = getattr(request.state, "staff", None)
        return str(staff.user_id) if staff is not None else None


def _too_many(retry_after: int) -> Response:
    return PlainTextResponse(
        "Too many failed logins. Try again later.",
        status_code=429,
        headers={"Retry-After": str(max(1, retry_after))},
    )
