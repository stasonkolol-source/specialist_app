"""Центр уведомлений и настройки по HTTP (DEVELOPMENT_PLAN 2.3a, ARCHITECTURE §8.5).

Приложение целиком на PostgreSQL и Valkey из testcontainers: вход — как у Mini App,
уведомления создаёт тот же use case, что и подписчики событий. Данные коммитятся, поэтому
у каждого теста свой Telegram id и IP.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from tests.plugins.http import HttpApp, http_app
from tests.plugins.identity import bearer, login, new_telegram_id, signed_init_data, user_id_of

from app.modules.identity.http.router import router as identity_router
from app.modules.notifications.application.use_cases.notify import Notify, NotifyCommand
from app.modules.notifications.domain.catalog import NotificationType
from app.modules.notifications.http.router import router
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings

pytestmark = pytest.mark.integration

CENTER = "/api/v1/me/notifications"
READ = "/api/v1/me/notifications/read"
SETTINGS = "/api/v1/me/notification-settings"


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[HttpApp]:
    ip = f"10.{new_id().int % 250}.{new_id().int % 250}.{new_id().int % 250}"
    async with http_app(settings, identity_router, router, client_ip=ip) as app:
        yield app


async def signed_in(app: HttpApp, settings: Settings) -> tuple[UserId, dict[str, str]]:
    tokens = await login(app.client, signed_init_data(settings, new_telegram_id()))
    return user_id_of(tokens), bearer(tokens)


async def restrict(app: HttpApp, user_id: UserId, kind: str) -> None:
    async with app.container() as request:
        notify = await request.get(Notify)
        await notify(
            NotifyCommand(
                user_id=user_id,
                type=NotificationType.ACCOUNT_RESTRICTED,
                dedupe_key=f"account.restricted:{new_id()}",
                params={"kind": kind},
                link="l_terms",
            )
        )


def settings_body(**changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "groups": [],
        "quiet_hours": {"enabled": True, "start": "22:00", "end": "08:00"},
        "digest_hour": 9,
    }
    return body | changes


async def test_center_pages_in_the_request_language_and_marks_read(
    app: HttpApp, settings: Settings
) -> None:
    user_id, headers = await signed_in(app, settings)
    await restrict(app, user_id, "posting_blocked")
    await restrict(app, user_id, "banned")

    first = await app.client.get(
        CENTER, params={"limit": 1}, headers=headers | {"accept-language": "sr-Latn"}
    )

    assert first.status_code == 200, first.text
    page = first.json()
    assert page["unread_count"] == 2
    [item] = page["items"]
    assert (item["type"], item["title"], item["read"]) == (
        "account.restricted",
        "Nalog je blokiran",
        False,
    )
    assert item["link"] == "l_terms"
    rest = await app.client.get(
        CENTER, params={"limit": 1, "cursor": page["next_cursor"]}, headers=headers
    )
    assert [i["title"] for i in rest.json()["items"]] == ["Аккаунт ограничен"]  # ru по умолчанию
    assert rest.json()["next_cursor"] is None

    read = await app.client.post(READ, json={"ids": [item["id"]]}, headers=headers)
    assert (read.status_code, read.json()) == (200, {"unread_count": 1})
    everything = await app.client.post(READ, json={"all": True}, headers=headers)
    assert everything.json() == {"unread_count": 0}


async def test_read_needs_ids_or_all(app: HttpApp, settings: Settings) -> None:
    _, headers = await signed_in(app, settings)

    for body in ({}, {"ids": [str(new_id())], "all": True}):
        response = await app.client.post(READ, json=body, headers=headers)
        assert response.status_code == 422, body


async def test_settings_default_then_saved(app: HttpApp, settings: Settings) -> None:
    _, headers = await signed_in(app, settings)

    defaults = await app.client.get(SETTINGS, headers=headers)

    assert defaults.status_code == 200, defaults.text
    body = defaults.json()
    groups = {g["group"]: g for g in body["groups"]}
    assert groups["marketing"] == {
        "group": "marketing",
        "telegram": False,
        "in_app": False,
        "mandatory": False,
    }
    # запуск «Вещей» (S58, 7.5) — только по согласию, как новости
    assert (groups["goods_launch"]["telegram"], groups["goods_launch"]["in_app"]) == (False, False)
    assert groups["account"]["mandatory"] is True
    assert body["quiet_hours"] == {
        "enabled": True,
        "start": "22:00:00",
        "end": "08:00:00",
        "time_zone": "Europe/Belgrade",
    }
    assert body["telegram"] is None  # боту писать ещё не разрешали

    saved = await app.client.put(
        SETTINGS,
        json=settings_body(
            groups=[{"group": "job_matches", "telegram": False, "in_app": True}],
            quiet_hours={"enabled": False, "start": "23:00", "end": "07:00"},
            digest_hour=7,
        ),
        headers=headers,
    )

    assert saved.status_code == 200, saved.text
    again = (await app.client.get(SETTINGS, headers=headers)).json()
    assert again == saved.json()
    job_matches = next(g for g in again["groups"] if g["group"] == "job_matches")
    assert (job_matches["telegram"], job_matches["in_app"]) == (False, True)
    assert (again["quiet_hours"]["enabled"], again["digest_hour"]) == (False, 7)


async def test_settings_refuse_turning_off_service_notifications(
    app: HttpApp, settings: Settings
) -> None:
    _, headers = await signed_in(app, settings)

    response = await app.client.put(
        SETTINGS,
        json=settings_body(groups=[{"group": "account", "telegram": False, "in_app": True}]),
        headers=headers,
    )

    assert response.status_code == 422
    assert (response.json()["code"], response.json()["group"]) == (
        "notification_group_mandatory",
        "account",
    )


@pytest.mark.parametrize(
    "body",
    [
        settings_body(quiet_hours={"enabled": True, "start": "08:00", "end": "08:00"}),
        settings_body(digest_hour=24),
        settings_body(groups=[{"group": "deals", "telegram": True, "in_app": True}] * 2),
        settings_body(groups=[{"group": "goods", "telegram": True, "in_app": True}]),
    ],
    ids=["empty-window", "hour", "duplicate", "unknown-group"],
)
async def test_settings_validate_input(
    app: HttpApp, settings: Settings, body: dict[str, Any]
) -> None:
    _, headers = await signed_in(app, settings)

    response = await app.client.put(SETTINGS, json=body, headers=headers)

    assert response.status_code == 422, response.text


async def test_center_and_settings_need_a_session(app: HttpApp) -> None:
    for method, path in (("GET", CENTER), ("GET", SETTINGS), ("POST", READ)):
        response = await app.client.request(method, path, json={"all": True})
        assert response.status_code == 401, path
