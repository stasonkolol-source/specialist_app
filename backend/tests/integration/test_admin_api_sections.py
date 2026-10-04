"""Admin API, часть 2 (DEVELOPMENT_PLAN 2.7b): справочники, контент-правила, рассылки, флаги и
client-config — только admin, тем же путём, что разделы SQLAdmin.

Правка справочника: поля формы раздела, название LocalizedText (`name_origin = admin`), аудит
`<модуль>.<объект>.updated`, у категорий и тегов — CatalogChanged (задача переиндексации).
Контент-правило проверяет та же `compile_rule` с RE2, что и сид; проба ничего не пишет. Рассылки —
use cases модуля notifications с аудитом. Флаг только переключается, client-config — с той же
проверкой формата. Moderator и support на всё это получают 403.

Данные коммитятся: тест возвращает справочники и конфигурацию как было.
"""

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from sqlalchemy import select, text, update

from app.platform.db.platform_tables import client_config, feature_flags
from app.platform.kernel.ids import new_id
from tests.plugins.admin import Admin, Staff, audit_count, login, staff
from tests.plugins.admin import client_ip as _ip

pytestmark = pytest.mark.integration

API = "/admin/api/v1"
WRITE = {"X-Requested-With": "sosed-admin"}


@asynccontextmanager
async def _signed_in(admin: Admin, who: Staff) -> AsyncIterator[httpx.AsyncClient]:
    async with admin.client(_ip()) as client:
        assert await login(client, who) == 302
        yield client


async def _one(admin: Admin, sql: str, **params: Any) -> Any:
    async with (await admin.engine()).begin() as conn:
        return (await conn.execute(text(sql), params)).one()


async def _execute(admin: Admin, sql: str, **params: Any) -> int:
    async with (await admin.engine()).begin() as conn:
        result = await conn.execute(text(sql), params)
    return int(result.rowcount or 0)


def _problem(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = response.json()
    assert body["code"] == code
    return body


def _sections() -> Iterator[tuple[str, str, dict[str, Any] | None]]:
    yield "GET", "/categories", None
    yield "PATCH", "/categories/1", {"is_active": True}
    yield "GET", "/tags", None
    yield "PATCH", "/tags/1", {"is_active": True}
    yield "GET", "/search-terms", None
    yield "GET", "/cities", None
    yield "PATCH", "/cities/1", {"sort_order": 1}
    yield "GET", "/districts", None
    yield "PATCH", "/districts/1", {"is_active": True}
    yield "GET", "/content-rules", None
    yield (
        "POST",
        "/content-rules",
        {"kind": "word", "pattern": "x", "action": "flag", "category": "spam"},
    )
    yield "PATCH", "/content-rules/1", {"is_active": True}
    yield (
        "POST",
        "/content-rules/trial",
        {"kind": "word", "pattern": "x", "action": "flag", "category": "spam"},
    )
    yield "GET", "/broadcasts", None
    yield "POST", "/broadcasts", {"text": {"ru": "x", "sr-Latn": "x"}}
    yield "GET", f"/broadcasts/{new_id()}", None
    yield "POST", f"/broadcasts/{new_id()}/test", {"locale": "ru"}
    yield "POST", f"/broadcasts/{new_id()}/start", {}
    yield "POST", f"/broadcasts/{new_id()}/cancel", None
    yield "GET", "/feature-flags", None
    yield "PATCH", "/feature-flags/platform.maintenance", {"enabled": True}
    yield "GET", "/client-config", None
    yield "PUT", "/client-config/min_versions", {"value": {"tma": "1.0.0"}}


@pytest.mark.authz
async def test_authz_reference_data_rules_broadcasts_and_config_are_admin_only(
    admin: Admin,
) -> None:
    for role in ("moderator", "support"):
        who = await staff(admin, role)
        async with _signed_in(admin, who) as client:
            for method, path, body in _sections():
                response = await client.request(method, f"{API}{path}", json=body, headers=WRITE)
                _problem(response, 403, "forbidden")
    owner = await staff(admin, "admin")
    async with _signed_in(admin, owner) as client:
        for path in (
            "/categories",
            "/tags",
            "/search-terms",
            "/cities",
            "/districts",
            "/content-rules",
            "/broadcasts",
            "/feature-flags",
            "/client-config",
        ):
            assert (await client.get(f"{API}{path}")).status_code == 200, path
        # словарь поиска принадлежит сидам: правки нет
        assert (
            await client.patch(f"{API}/search-terms/1", json={}, headers=WRITE)
        ).status_code in {
            404,
            405,
        }


@pytest.mark.authz
async def test_authz_category_and_tag_edits_go_the_sqladmin_way(admin: Admin) -> None:
    owner = await staff(admin, "admin")
    category = (
        await _one(
            admin,
            "INSERT INTO catalog.categories (slug, name) VALUES"
            ' (:slug, \'{"ru": "Тест", "sr-Cyrl": "Тест"}\') RETURNING id',
            slug=f"api-test-{new_id().hex[:8]}",
        )
    )[0]
    tag = (
        await _one(
            admin,
            "INSERT INTO catalog.tags (category_id, slug, name) VALUES (:category, :slug,"
            ' \'{"ru": "Тег", "sr-Cyrl": "Тег", "sr-Latn": "Teg"}\') RETURNING id',
            category=category,
            slug=f"api-tag-{new_id().hex[:8]}",
        )
    )[0]
    try:
        async with _signed_in(admin, owner) as client:
            edited = await client.patch(
                f"{API}/categories/{category}",
                json={"max_responses": 3, "name": {"ru": "Тест правка", "sr-Latn": ""}},
                headers=WRITE,
            )
            assert edited.status_code == 200, edited.text
            body = edited.json()
            assert body["max_responses"] == 3
            # пустая латиница — транслит кириллицы; название теперь ведёт админка
            assert body["name"] == {"ru": "Тест правка", "sr-Cyrl": "Тест", "sr-Latn": "Test"}
            assert body["name_origin"] == "admin"
            empty = await client.patch(
                f"{API}/categories/{category}",
                json={"name": {"ru": "", "sr-Cyrl": ""}},
                headers=WRITE,
            )
            assert "Название" in _problem(empty, 422, "invalid_admin_change")["reason"]
            listed = await client.get(f"{API}/tags", params={"category_id": category})
            assert [item["id"] for item in listed.json()["items"]] == [tag]
            off = await client.patch(f"{API}/tags/{tag}", json={"is_active": False}, headers=WRITE)
            assert off.json()["is_active"] is False
            assert off.json()["name_origin"] == "seed"  # название не трогали
            _problem(
                await client.patch(f"{API}/categories/0", json={}, headers=WRITE), 404, "not_found"
            )
        jobs = await _execute(
            admin,
            "DELETE FROM procrastinate_jobs WHERE task_name = 'search.on_catalog_changed'"
            " AND status = 'todo' AND args->'payload'->'category_ids' @> jsonb_build_array("
            "CAST(:id AS integer))",
            id=category,
        )
        assert jobs >= 1  # CatalogChanged: переиндексация поиска по категории
    finally:
        # база общая на прогон: лишний раздел сбил бы счёт сидов в test_catalog_seeds
        await _execute(admin, "DELETE FROM catalog.tags WHERE id = :id", id=tag)
        await _execute(admin, "DELETE FROM catalog.categories WHERE id = :id", id=category)
    assert await audit_count(admin, "catalog.category.updated", owner.user_id) == 1
    assert await audit_count(admin, "catalog.tag.updated", owner.user_id) == 1


@pytest.mark.authz
async def test_authz_cities_and_districts_are_edited_with_audit(admin: Admin) -> None:
    owner = await staff(admin, "admin")
    slug = f"api-city-{new_id().hex[:8]}"
    name = json.dumps({"ru": "Тест", "sr-Cyrl": "Тест", "sr-Latn": "Test"})
    point = "ST_GeogFromText('SRID=4326;POINT(20.46 44.81)')"
    city = (
        await _one(
            admin,
            "INSERT INTO geo.cities (slug, name, center, is_active, sort_order) VALUES"
            f" (:slug, CAST(:name AS jsonb), {point}, false, 5) RETURNING id",
            slug=slug,
            name=name,
        )
    )[0]
    district = (
        await _one(
            admin,
            "INSERT INTO geo.districts (city_id, kind, slug, name, center, source) VALUES"
            f" (:city, 'municipality', :slug, CAST(:name AS jsonb), {point}, 'test') RETURNING id",
            city=city,
            slug=f"{slug}-d",
            name=name,
        )
    )[0]
    try:
        async with _signed_in(admin, owner) as client:
            launched = await client.patch(
                f"{API}/cities/{city}",
                json={"is_active": True, "sort_order": 6, "name": {"en": "Test city"}},
                headers=WRITE,
            )
            assert launched.status_code == 200, launched.text
            body = launched.json()
            assert (body["is_active"], body["sort_order"]) == (True, 6)
            assert body["name"]["en"] == "Test city"
            assert body["name_origin"] == "admin"
            assert "center" not in body  # центры и границы — у сидов
            listed = await client.get(f"{API}/districts", params={"city_id": city})
            assert [item["id"] for item in listed.json()["items"]] == [district]
            off = await client.patch(
                f"{API}/districts/{district}", json={"is_active": False}, headers=WRITE
            )
            assert off.json()["is_active"] is False
            assert off.json()["name_origin"] == "seed"  # название не трогали
    finally:
        await _execute(admin, "DELETE FROM geo.districts WHERE id = :id", id=district)
        await _execute(admin, "DELETE FROM geo.cities WHERE id = :id", id=city)
    assert await audit_count(admin, "geo.city.updated", owner.user_id) == 1
    assert await audit_count(admin, "geo.district.updated", owner.user_id) == 1


@pytest.mark.authz
async def test_authz_content_rules_are_checked_like_the_seed_and_tried_first(
    admin: Admin,
) -> None:
    owner = await staff(admin, "admin")
    word = f"zabranjeno{new_id().hex[:6]}"
    created_ids: list[int] = []
    try:
        async with _signed_in(admin, owner) as client:
            tried = await client.post(
                f"{API}/content-rules/trial",
                json={
                    "kind": "word",
                    "pattern": word,
                    "action": "flag",
                    "category": "scam",
                    "sample": f"prodajem {word} jeftino",
                },
                headers=WRITE,
            )
            assert tried.status_code == 200, tried.text
            assert tried.json()["error"] is None
            assert tried.json()["hit"] is True
            assert tried.json()["examples"] > 0
            created = await client.post(
                f"{API}/content-rules",
                json={
                    "kind": "word",
                    "pattern": word.upper(),
                    "action": "flag",
                    "category": "scam",
                },
                headers=WRITE,
            )
            assert created.status_code == 201, created.text
            rule = created.json()
            created_ids.append(rule["id"])
            assert (rule["pattern"], rule["origin"], rule["is_active"]) == (word, "admin", True)
            # регулярку не собирает RE2 — та же причина, что у seeds-validate
            bad = await client.post(
                f"{API}/content-rules",
                json={"kind": "regex", "pattern": "(?<=a)b", "action": "flag", "category": "spam"},
                headers=WRITE,
            )
            assert "Правило не принято" in _problem(bad, 422, "invalid_admin_change")["reason"]
            again = await client.post(
                f"{API}/content-rules",
                json={"kind": "word", "pattern": word, "action": "flag", "category": "scam"},
                headers=WRITE,
            )
            _problem(again, 422, "invalid_admin_change")  # такое правило уже есть
            off = await client.patch(
                f"{API}/content-rules/{rule['id']}", json={"is_active": False}, headers=WRITE
            )
            assert off.json()["is_active"] is False
            assert off.json()["pattern"] == word
            found = await client.get(f"{API}/content-rules", params={"q": word})
            assert [item["id"] for item in found.json()["items"]] == [rule["id"]]
    finally:
        for rule_id in created_ids:
            await _execute(admin, "DELETE FROM moderation.content_rules WHERE id = :id", id=rule_id)
    assert await audit_count(admin, "moderation.content_rule.created", owner.user_id) == 1
    assert await audit_count(admin, "moderation.content_rule.updated", owner.user_id) == 1


async def test_admin_api_content_rule_saved_unchanged_stays_with_the_seed(admin: Admin) -> None:
    """«Сохранить» без правок строку сида админке не передаёт (её и дальше ведёт `cli seed`), а
    настоящая правка — передаёт; ключ сида при этом остаётся, исходное правило не вернётся."""
    owner = await staff(admin, "admin")
    word = f"seedword{new_id().hex[:6]}"
    rule_id = (
        await _one(
            admin,
            "INSERT INTO moderation.content_rules (pattern, kind, action, category, origin,"
            " seed_key) VALUES (:word, 'word', 'flag', 'spam', 'seed', :key) RETURNING id",
            word=word,
            key=f"word:{word}",
        )
    )[0]
    try:
        async with _signed_in(admin, owner) as client:
            path = f"{API}/content-rules/{rule_id}"
            same = await client.patch(path, json={"pattern": word.upper()}, headers=WRITE)
            assert same.status_code == 200, same.text
            assert same.json()["origin"] == "seed"  # слово и так в нижнем регистре
            assert (await client.patch(path, json={}, headers=WRITE)).json()["origin"] == "seed"
            edited = await client.patch(path, json={"pattern": f"{word}x"}, headers=WRITE)
            assert edited.json()["origin"] == "admin"
        row = await _one(
            admin, "SELECT seed_key FROM moderation.content_rules WHERE id = :id", id=rule_id
        )
        assert row.seed_key == f"word:{word}"
    finally:
        await _execute(admin, "DELETE FROM moderation.content_rules WHERE id = :id", id=rule_id)


@pytest.mark.authz
async def test_authz_broadcasts_go_through_the_notifications_use_cases(admin: Admin) -> None:
    owner = await staff(admin, "admin")
    async with _signed_in(admin, owner) as client:
        created = await client.post(
            f"{API}/broadcasts",
            json={"text": {"ru": "Новости <b>Соседей</b>", "sr-Latn": "Vesti Suseda"}},
            headers=WRITE,
        )
        assert created.status_code == 201, created.text
        card = created.json()
        broadcast_id = card["broadcast"]["id"]
        assert card["broadcast"]["status"] == "draft"
        assert [preview["locale"] for preview in card["previews"]] == ["ru", "sr-Latn", "sr-Cyrl"]
        assert "&lt;b&gt;" in card["previews"][0]["text"]  # без разметки: экранируется целиком
        assert card["stats"]["recipients"] == 0
        listed = await client.get(f"{API}/broadcasts", params={"limit": 5})
        assert broadcast_id in [item["id"] for item in listed.json()["items"]]
        tested = await client.post(
            f"{API}/broadcasts/{broadcast_id}/test", json={"locale": "ru"}, headers=WRITE
        )
        # тест — тем же use case, что в SQLAdmin: боту некуда писать сотруднику без /start
        _problem(tested, 409, "telegram_not_linked")
        started = await client.post(
            f"{API}/broadcasts/{broadcast_id}/start",
            json={"at": "2099-01-01T10:00:00+01:00"},
            headers=WRITE,
        )
        assert started.json() == {"status": "scheduled"}
        cancelled = await client.post(f"{API}/broadcasts/{broadcast_id}/cancel", headers=WRITE)
        assert cancelled.json() == {"suppressed": 0}
        _problem(await client.get(f"{API}/broadcasts/{new_id()}"), 404, "broadcast_not_found")
    await _execute(
        admin,
        "DELETE FROM procrastinate_jobs WHERE status = 'todo' AND args::text LIKE :id",
        id=f"%{broadcast_id}%",
    )
    for action in ("created", "started", "cancelled"):
        assert await audit_count(admin, f"notifications.broadcast.{action}", owner.user_id) == 1


@pytest.mark.authz
async def test_authz_flag_toggle_and_client_config_are_checked_and_audited(
    admin: Admin,
) -> None:
    owner = await staff(admin, "admin")
    key = f"test.api-{new_id().hex[:8]}"
    engine = await admin.engine()
    async with engine.begin() as conn:
        await conn.execute(
            feature_flags.insert().values(key=key, enabled=False, public=True, description="тест")
        )
        saved = (
            await conn.execute(
                select(client_config.c.value).where(client_config.c.key == "min_versions")
            )
        ).scalar_one_or_none()
    try:
        async with _signed_in(admin, owner) as client:
            toggled = await client.patch(
                f"{API}/feature-flags/{key}", json={"enabled": True}, headers=WRITE
            )
            assert toggled.status_code == 200, toggled.text
            assert toggled.json()["enabled"] is True
            assert toggled.json()["updated_by"] == str(owner.user_id)
            public = await client.get("/api/v1/client-config")
            assert public.json()["flags"][key] is True  # этот процесс видит правку сразу
            _problem(
                await client.patch(
                    f"{API}/feature-flags/test.none", json={"enabled": True}, headers=WRITE
                ),
                404,
                "not_found",
            )
            if saved is not None:
                wrong = await client.put(
                    f"{API}/client-config/min_versions",
                    json={"value": {"tma": "one"}},
                    headers=WRITE,
                )
                assert "min_versions" in _problem(wrong, 422, "invalid_admin_change")["reason"]
                ok = await client.put(
                    f"{API}/client-config/min_versions",
                    json={"value": {"tma": "0.0.1"}},
                    headers=WRITE,
                )
                assert ok.status_code == 200, ok.text
                assert (ok.json()["value"], ok.json()["editable"]) == ({"tma": "0.0.1"}, True)
    finally:
        async with engine.begin() as conn:
            await conn.execute(feature_flags.delete().where(feature_flags.c.key == key))
            if saved is not None:
                await conn.execute(
                    update(client_config)
                    .where(client_config.c.key == "min_versions")
                    .values(value=saved)
                )
    assert await audit_count(admin, "platform.feature_flag.updated", owner.user_id) == 1
    expected = 1 if saved is not None else 0
    assert await audit_count(admin, "platform.client_config.updated", owner.user_id) == expected
