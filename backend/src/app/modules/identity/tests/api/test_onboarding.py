"""Онбординг по HTTP: согласия, «можно ли», город и намерение (DEVELOPMENT_PLAN 1.4a).

Создающих эндпоинтов у identity нет, поэтому «можно ли» проверяет тестовый маршрут —
так же, как будут звать фасад заявки, отклики и сообщения. Версии документов — из
client-config (миграция platform_0007: утверждённая редакция «1»).
"""

from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import pytest
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from tests.plugins.http import HttpApp, http_app, sample_router
from tests.plugins.round_trips import round_trips

from app.modules.geo.http.router import router as geo_router
from app.modules.identity.api import Action, IdentityApi, RestrictionIn, RestrictionKind
from app.modules.identity.http.router import router
from app.platform.db.port import UnitOfWork
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.ids import UserId, new_id
from app.platform.kernel.principal import Principal
from app.platform.settings import Settings

from .conftest import InitData, bearer, login

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("geo_seeded")]

TICK = {"terms_version": "1", "privacy_version": "1"}

probe = sample_router()


@probe.post("/jobs", status_code=status.HTTP_204_NO_CONTENT, dependencies=AUTHENTICATED)
@inject
async def create_job(principal: FromDishka[Principal], identity: FromDishka[IdentityApi]) -> None:
    """Как начнёт use case публикации заявки: сначала единая точка «можно ли»."""
    await identity.ensure_allowed(principal.user_id, Action.POST)


@pytest.fixture
def client_ip() -> str:
    """Свой адрес на тест: лимиты /auth/* считаются по IP."""
    return f"10.{new_id().int % 250}.{new_id().int % 250}.{new_id().int % 250}"


@pytest.fixture
async def app(settings: Settings, client_ip: str) -> AsyncIterator[HttpApp]:
    async with http_app(settings, router, geo_router, probe, client_ip=client_ip) as app:
        yield app


@pytest.fixture
def api(app: HttpApp) -> httpx.AsyncClient:
    return app.client


async def consent_rows(app: HttpApp, user_id: str) -> list[tuple[str, str, str, str]]:
    async with app.container() as request:
        session = await request.get(AsyncSession)
        rows = await session.execute(
            text(
                "SELECT document, version, source, host(ip) FROM identity.consents"
                " WHERE user_id = :user_id ORDER BY document"
            ),
            {"user_id": user_id},
        )
        return [tuple(row) for row in rows]


async def restrict(app: HttpApp, user_id: str, kind: RestrictionKind) -> None:
    """Санкция, как её поставит модерация (2.5a): фасад в транзакции вызывающего."""
    async with app.container() as request:
        uow = await request.get(UnitOfWork)
        identity = await request.get(IdentityApi)
        async with uow:
            await identity.restrict(
                RestrictionIn(user_id=UserId(UUID(user_id)), kind=kind, reason_code="spam")
            )


async def city_id(api: httpx.AsyncClient, slug: str) -> int:
    cities = (await api.get("/api/v1/cities")).json()
    return int(next(c["id"] for c in cities if c["slug"] == slug))


# --- согласия ------------------------------------------------------------------------------


async def test_consent_unlocks_creating_actions(app: HttpApp, init_data: InitData) -> None:
    api = app.client
    tokens = await login(api, init_data())
    auth = bearer(tokens)

    refused = await api.post("/api/v1/test/jobs", headers=auth)
    assert refused.status_code == 403
    assert refused.headers["content-type"] == "application/problem+json"
    problem = refused.json()
    assert (problem["code"], problem["documents"]) == (
        "consent_required",
        ["age_18", "privacy", "terms"],
    )
    me = (await api.get("/api/v1/me", headers=auth)).json()
    assert (me["consent_required"], me["can_post_jobs"], me["consents"]) == (True, False, {})

    accepted = await api.post("/api/v1/me/consents", headers=auth, json=TICK)
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["consents"] == {"terms": "1", "privacy": "1", "age_18": "1"}
    assert (body["consent_required"], body["can_post_jobs"], body["can_respond"]) == (
        False,
        True,
        True,
    )
    assert accepted.headers["etag"] == '"1"'
    assert (await api.post("/api/v1/test/jobs", headers=auth)).status_code == 204


async def test_repeated_consent_is_idempotent(
    app: HttpApp, init_data: InitData, client_ip: str
) -> None:
    api = app.client
    tokens = await login(api, init_data())
    user_id = str((await api.get("/api/v1/me", headers=bearer(tokens))).json()["id"])

    first = await api.post("/api/v1/me/consents", headers=bearer(tokens), json=TICK)
    again = await api.post("/api/v1/me/consents", headers=bearer(tokens), json=TICK)

    assert (first.status_code, again.status_code) == (200, 200)
    assert again.json() == first.json()
    assert await consent_rows(app, user_id) == [
        ("age_18", "1", "tma", client_ip),
        ("privacy", "1", "tma", client_ip),
        ("terms", "1", "tma", client_ip),
    ]


@pytest.mark.parametrize(
    ("body", "status_code", "problem"),
    [
        (
            # Mini App со старым client-config: черновик после утверждения редакции «1»
            {"terms_version": "draft-1", "privacy_version": "1"},
            409,
            {"code": "legal_version_outdated", "document": "terms", "current": "1"},
        ),
        ({"terms_version": "1"}, 422, {"code": "validation_error"}),
        ({"terms_version": "", "privacy_version": "1"}, 422, {"code": "validation_error"}),
    ],
)
async def test_consent_with_wrong_versions_is_refused(
    app: HttpApp,
    init_data: InitData,
    body: dict[str, str],
    status_code: int,
    problem: dict[str, str],
) -> None:
    """409 называет документ и действующую версию: клиенту не нужен client-config из кэша."""
    api = app.client
    tokens = await login(api, init_data())
    response = await api.post("/api/v1/me/consents", headers=bearer(tokens), json=body)
    assert response.status_code == status_code
    assert problem.items() <= response.json().items()
    assert (await api.get("/api/v1/me", headers=bearer(tokens))).json()["consent_required"]


async def test_consent_needs_login(api: httpx.AsyncClient) -> None:
    response = await api.post("/api/v1/me/consents", json=TICK)
    assert response.status_code == 401


# --- санкции -------------------------------------------------------------------------------


async def test_restricted_user_gets_403_restricted(app: HttpApp, init_data: InitData) -> None:
    api = app.client
    tokens = await login(api, init_data())
    auth = bearer(tokens)
    await api.post("/api/v1/me/consents", headers=auth, json=TICK)
    user_id = str((await api.get("/api/v1/me", headers=auth)).json()["id"])

    await restrict(app, user_id, RestrictionKind.POSTING_BLOCKED)

    refused = await api.post("/api/v1/test/jobs", headers=auth)
    assert refused.status_code == 403
    assert (refused.json()["code"], refused.json()["restriction"], refused.json()["until"]) == (
        "restricted",
        "posting_blocked",
        None,
    )
    me = (await api.get("/api/v1/me", headers=auth)).json()
    assert (me["consent_required"], me["can_post_jobs"], me["can_respond"]) == (False, False, True)


async def test_login_and_me_read_profile_once(app: HttpApp, init_data: InitData) -> None:
    """Перф-аудит: GET /me — один запрос (профиль, санкции, согласия); повторный вход отвечает
    профилем из своей транзакции, без чтений после commit, и не пишет неизменный профиль."""
    api = app.client
    tokens = await login(api, init_data())
    auth = bearer(tokens)
    await api.post("/api/v1/me/consents", headers=auth, json=TICK)
    user_id = str((await api.get("/api/v1/me", headers=auth)).json()["id"])
    await restrict(app, user_id, RestrictionKind.POSTING_BLOCKED)
    engine = await app.container.get(AsyncEngine)

    with round_trips(engine) as trips:
        me = await api.get("/api/v1/me", headers=auth)
    assert trips.queries == 1
    assert trips.total == 2  # проверка соединения и запрос; было 12 (3 чтения по 4 обмена)
    with round_trips(engine) as trips:
        again = await login(api, init_data())
    # пользователь (строка и способы входа), санкции, новая сессия, роли и согласия
    assert trips.queries == 5, trips.statements
    assert trips.total == 8  # pre-ping, BEGIN, 5 запросов, COMMIT; было 22
    assert again["user"] == me.json()
    assert (me.json()["consent_required"], me.json()["can_post_jobs"]) == (False, False)
    assert set(me.json()["consents"]) == {"terms", "privacy", "age_18"}


# --- город и намерение ---------------------------------------------------------------------


async def test_onboarding_sets_city_and_intent(api: httpx.AsyncClient, init_data: InitData) -> None:
    tokens = await login(api, init_data())
    novi_sad = await city_id(api, "novi-sad")
    me = await api.get("/api/v1/me", headers=bearer(tokens))
    assert (me.json()["home_city_id"], me.json()["intent"]) == (None, None)

    response = await api.patch(
        "/api/v1/me",
        headers=bearer(tokens) | {"if-match": me.headers["etag"]},
        json={"ui_locale": "sr-Cyrl", "home_city_id": novi_sad},
    )
    assert response.status_code == 200
    assert (response.json()["home_city_id"], response.json()["ui_locale"]) == (novi_sad, "sr-Cyrl")
    assert response.headers["etag"] == '"2"'

    response = await api.patch(
        "/api/v1/me", headers=bearer(tokens) | {"if-match": '"2"'}, json={"intent": "casual"}
    )
    assert (response.json()["intent"], response.json()["home_city_id"]) == ("casual", novi_sad)

    stale = await api.patch(
        "/api/v1/me", headers=bearer(tokens) | {"if-match": '"2"'}, json={"intent": "pro"}
    )
    assert stale.status_code == 412
    assert stale.json()["code"] == "stale_version"


@pytest.mark.parametrize(
    ("city", "code"),
    [("unknown", "unknown_city"), ("beograd", "city_not_available")],
)
async def test_city_must_exist_and_be_active(
    api: httpx.AsyncClient, init_data: InitData, city: str, code: str
) -> None:
    tokens = await login(api, init_data())
    home_city_id = 999_999 if city == "unknown" else await city_id(api, city)
    response = await api.patch(
        "/api/v1/me", headers=bearer(tokens), json={"home_city_id": home_city_id}
    )
    assert response.status_code == 422
    assert response.json()["code"] == code
    assert (await api.get("/api/v1/me", headers=bearer(tokens))).headers["etag"] == '"1"'


@pytest.mark.parametrize(
    ("body", "field", "code"),
    [
        ({"home_city_id": 0}, "home_city_id", "greater_than_equal"),
        ({"home_city_id": 2**31}, "home_city_id", "less_than_equal"),
        ({"intent": "buyer"}, "intent", "enum"),
    ],
)
async def test_city_and_intent_validation(
    api: httpx.AsyncClient, init_data: InitData, body: dict[str, object], field: str, code: str
) -> None:
    tokens = await login(api, init_data())
    response = await api.patch("/api/v1/me", headers=bearer(tokens), json=body)
    assert response.status_code == 422
    [error] = response.json()["errors"]
    assert (error["field"], error["code"]) == (field, code)
