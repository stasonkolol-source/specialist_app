"""Несуществующая категория прайса: 422 при создании и изменении, транзакция откатывается."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.pricing.http.router import router as pricing
from app.modules.specialists.http.router import router as specialists
from app.platform.kernel.ids import new_id
from app.platform.settings import Settings
from tests.plugins.http import bearer, http_app
from tests.plugins.identity import accept_rules, insert_user

pytestmark = pytest.mark.integration


async def test_unknown_price_category_is_a_field_error(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> None:
    async with http_app(storage_settings, specialists, pricing) as app:
        async with app.container() as request:
            session = await request.get(AsyncSession)
            user_id = await insert_user(session)
            await accept_rules(session, user_id)
            city_id = await session.scalar(
                text("SELECT id FROM geo.cities WHERE slug = 'novi-sad'")
            )
            category_id = await session.scalar(text("SELECT min(id) FROM catalog.categories"))
        headers = bearer(storage_settings, user_id)
        profile = await app.client.post(
            "/api/v1/me/profile",
            json={"kind": "pro", "city_id": city_id},
            headers=headers | {"idempotency-key": new_id().hex},
        )
        assert profile.status_code == 201, profile.text
        url = "/api/v1/me/profile/services"
        body = {
            "title": "Замена розетки",
            "price_type": "fixed",
            "price_min": 150_000,
            "category_id": category_id,
        }
        created = await app.client.post(
            url, json=body, headers=headers | {"idempotency-key": new_id().hex}
        )
        assert created.status_code == 201, created.text
        invalid = {"category_id": 2**31 - 1}

        added = await app.client.post(
            url, json=body | invalid, headers=headers | {"idempotency-key": new_id().hex}
        )
        changed = await app.client.patch(
            f"{url}/{created.json()['id']}", json=invalid, headers=headers
        )

        for response in (added, changed):
            assert response.status_code == 422, response.text
            assert response.json()["code"] == "invalid_service"
            assert response.json()["field"] == "category_id"
        listed = await app.client.get(url, headers=headers)
        assert listed.status_code == 200, listed.text
        assert listed.json()["items"] == [created.json()]
