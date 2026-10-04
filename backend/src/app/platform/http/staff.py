"""Персонал в Admin API `/admin/api/v1` (DEVELOPMENT_PLAN 2.7b; ARCHITECTURE §8.5, §13.2; ADR-0009).

- Сессия — та же подписанная cookie `sosed_admin`, что у SQLAdmin: вход с паролем и TOTP — только
  страница /admin/login, у API своего входа и bearer-токенов нет. Ключ, срок и флаги cookie — здесь,
  их берут обе стороны (interfaces/admin и interfaces/http/admin_api.py). Сотрудника кладёт в
  `request.state.staff` зависимость сборки Admin API на каждом запросе: роли перечитываются из
  `identity.user_roles`, снятая роль закрывает API сразу.
- Роль операции — `staff_only(roles)`: проверка (403 `forbidden`) и `x-staff-roles` в схеме
  admin-openapi.json — по нему архитектурный тест сверяет каждую операцию с тестом прав.
- CSRF. Cookie SameSite=Strict не уходит с чужих сайтов, но «сайт» — регистрируемый домен:
  страница другого поддомена (Mini App на <domain>, cdn.<domain>) её несёт. Поэтому меняющий
  запрос (POST, PUT, PATCH, DELETE) обязан прислать заголовок `X-Requested-With: sosed-admin`
  (OWASP CSRF Cheat Sheet, «custom request headers»): форма чужой страницы его не поставит, а
  fetch с ним с другого origin упрётся в CORS-preflight — CORS у API нет. Сверх того, если браузер
  прислал Fetch Metadata или Origin, запрос должен быть same-origin. Отказ — 403 `csrf_rejected`.
  GET с побочным действием (просмотр ПД с аудитом и лимитом, доказательства спора с блокировкой
  кейса) заголовка не требует — его открывают и ссылкой, — но Fetch Metadata и Origin проверяются
  так же (`staff_only(..., side_effects=True)`): `<img>` страницы поддомена не потратит лимит ПД и
  не напишет аудит от имени сотрудника. SQLAdmin `/admin` — те же правила (`foreign_request`,
  interfaces/admin/app.py).
- Лимит — на сотрудника, субъект `staff:<id>`, а не `user:`: превышение у персонала не пишет
  сигналов риска модерации. Просмотр ПД — свой, более узкий лимит (выгрузка базы через карточки).
"""

from collections.abc import Mapping
from typing import Any, Final
from urllib.parse import urlsplit

from fastapi import Depends, Request

from app.platform.http.admin import container_of, staff_id, staff_roles
from app.platform.kernel.errors import ForbiddenError
from app.platform.kernel.principal import Role
from app.platform.ratelimit import Rate, RateLimiter
from app.platform.security.errors import CsrfRejectedError
from app.platform.settings import AppSettings, Environment

SESSION_COOKIE: Final = "sosed_admin"
SESSION_KEY: Final = "staff"
"""Ключ сессии с id сотрудника."""
SESSION_MAX_AGE: Final = 8 * 3600
DEV_SESSION_KEY: Final = "sosed-dev-admin-session-key"
"""Ключ cookie без APP_ADMIN_SESSION_KEY — только dev и тесты."""
PUBLISHED: Final = (Environment.STAGE, Environment.PRODUCTION)

PERSONAL_DATA: Final = frozenset({Role.SUPPORT, Role.ADMIN})
"""Кто видит ПД в карточке пользователя (имя, телефон, Telegram); каждый просмотр — в аудит."""

CSRF_HEADER: Final = "X-Requested-With"
CSRF_VALUE: Final = "sosed-admin"
SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})
SAME_ORIGIN: Final = frozenset({"same-origin"})
"""Sec-Fetch-Site меняющего запроса Admin API: только своя страница (fetch админки)."""
OWN_OR_TYPED: Final = frozenset({"same-origin", "none"})
"""Sec-Fetch-Site перехода, который не подделать чужой страницей: своя страница или адресная
строка и закладка сотрудника (none). Страница поддомена даёт same-site, чужой сайт — cross-site."""

STAFF_REQUESTS: Final = Rate("admin.api", "600/minute")
PERSONAL_DATA_VIEWS: Final = Rate("admin.pii_views", "120/hour")


def session_secret(app: AppSettings) -> str | None:
    """Ключ cookie персонала; None — на stage и проде без APP_ADMIN_SESSION_KEY: админка и
    Admin API там не монтируются (их публикуют только за Cloudflare Access, K31)."""
    key = app.admin_session_key
    if key is None:
        return None if app.env in PUBLISHED else DEV_SESSION_KEY
    return key.get_secret_value()


def staff_subject(request: Request) -> str:
    return f"staff:{staff_id(request)}"


class _RoleGuard:
    def __init__(self, roles: frozenset[Role]) -> None:
        self.roles = roles

    async def __call__(self, request: Request) -> None:
        if not staff_roles(request) & self.roles:
            raise ForbiddenError


def staff_only(roles: frozenset[Role], *, side_effects: bool = False) -> dict[str, Any]:
    """Параметры маршрута Admin API: `@router.get("/cases", **staff_only(MODERATION))`.
    `side_effects` — GET пишет аудит или блокирует строку: чужая страница его не вызовет."""
    dependencies = [Depends(_RoleGuard(roles))]
    if side_effects:
        dependencies.append(Depends(same_origin_read))
    return {
        "dependencies": dependencies,
        "openapi_extra": {"x-staff-roles": sorted(role.value for role in roles)},
    }


def foreign_request(headers: Mapping[str, str], sites: frozenset[str]) -> str | None:
    """Почему запрос не со своей страницы: `fetch_site` или `origin`; None — со своей. Браузер
    без Fetch Metadata и Origin (или не браузер) проходит: его закрывает cookie SameSite=Strict."""
    site = headers.get("sec-fetch-site")
    if site is not None and site not in sites:
        return "fetch_site"
    origin = headers.get("origin")
    if origin is not None and urlsplit(origin).netloc != headers.get("host"):
        return "origin"
    return None


async def csrf_guard(request: Request) -> None:
    """Меняющий запрос — только со своей страницы админки (см. docstring модуля)."""
    if request.method in SAFE_METHODS:
        return
    if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise CsrfRejectedError(reason="header")
    if reason := foreign_request(request.headers, SAME_ORIGIN):
        raise CsrfRejectedError(reason=reason)


async def same_origin_read(request: Request) -> None:
    """GET с побочным действием — не с чужой страницы (см. docstring модуля)."""
    if reason := foreign_request(request.headers, OWN_OR_TYPED):
        raise CsrfRejectedError(reason=reason)


async def staff_rate_limit(request: Request) -> None:
    """Общий лимит сотрудника на Admin API; заголовки RateLimit-* — как у публичного API."""
    limiter = await container_of(request).get(RateLimiter)
    request.state.rate_limit = await limiter.hit(STAFF_REQUESTS, staff_subject(request))


async def count_personal_data_view(request: Request) -> None:
    """Просмотр ПД сверх лимита — 429: карточки не выгружают базу целиком."""
    limiter = await container_of(request).get(RateLimiter)
    await limiter.hit(PERSONAL_DATA_VIEWS, staff_subject(request))
