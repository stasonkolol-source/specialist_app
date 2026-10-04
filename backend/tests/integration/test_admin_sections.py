"""Админка, вторая часть 2.7b: feature flags, client-config, Founding, названия справочников.

- Переключение флага пишет аудит и видно в GET /client-config без перезапуска.
- client-config: строка БД правится с проверкой формата и аудитом; значения окружения — только
  для чтения на странице итога; moderator разделов платформы не видит.
- Founding — use case SetFounding от имени сотрудника: отметка и снятие, обе — в аудите.
- Название, поправленное в админке (`name_origin = admin`), следующий `cli seed` не переписывает,
  а остальные поля строки сид обновляет.

Данные коммитятся (кроме теста сидов — он в транзакции теста): у каждого теста свои ключи, строки
и сотрудники, общее состояние (флаги, client-config) возвращается как было.
"""

import json
from collections.abc import AsyncIterator

import procrastinate
import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.modules.catalog.api import RiskLevel
from app.modules.catalog.application.dto import CategorySeed, TagSeed
from app.modules.catalog.infrastructure.writer import SqlCatalogWriter
from app.modules.geo.application.dto import CitySeed, DistrictSeed
from app.modules.geo.domain.place import DistrictKind
from app.modules.geo.infrastructure.writer import SqlGeoWriter
from app.platform.db.platform_tables import client_config, feature_flags
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import new_id
from app.platform.kernel.localized import Locale, LocalizedText
from tests.plugins.admin import Admin, audit_count, client_ip, login, staff
from tests.plugins.database import make_uow
from tests.plugins.identity import insert_user, new_telegram_id

pytestmark = pytest.mark.integration


@pytest.fixture
async def restore_config(migrator_engine: AsyncEngine) -> AsyncIterator[None]:
    """Вернуть client-config как было: версии документов из миграции нужны тестам identity."""
    async with migrator_engine.connect() as conn:
        rows = await conn.execute(select(client_config.c.key, client_config.c.value))
        saved = {row.key: row.value for row in rows}
    yield
    async with migrator_engine.begin() as conn:
        for key, value in saved.items():
            await conn.execute(
                update(client_config).where(client_config.c.key == key).values(value=value)
            )
        await conn.execute(feature_flags.delete().where(feature_flags.c.key.like("test.%")))


async def test_admin_flag_toggle_reaches_client_config(admin: Admin, restore_config: None) -> None:
    owner = await staff(admin, "admin")
    moderator = await staff(admin, "moderator")
    key = f"test.admin-{new_id().hex[:8]}"
    engine = await admin.engine()
    async with engine.begin() as conn:
        await conn.execute(
            feature_flags.insert().values(key=key, enabled=False, public=True, description="тест")
        )
    async with admin.client(client_ip()) as client:
        assert await login(client, moderator) == 302
        assert (await client.get("/admin/feature-flag-record/list")).status_code == 403
        assert (await client.get("/admin/client-config")).status_code == 403
    async with admin.client(client_ip()) as client:
        assert await login(client, owner) == 302
        listed = await client.get("/admin/feature-flag-record/list")
        assert listed.status_code == 200
        assert "max-age 60" in listed.text  # подсказка: правка доходит без релиза
        before = (await client.get("/api/v1/client-config")).json()["flags"]
        toggled = await client.post(f"/admin/feature-flag-record/edit/{key}", data={"enabled": "y"})
        assert toggled.status_code == 302, toggled.text[:500]
        after = (await client.get("/api/v1/client-config")).json()["flags"]
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                select(feature_flags.c.enabled, feature_flags.c.updated_by).where(
                    feature_flags.c.key == key
                )
            )
        ).one()
    assert before[key] is False
    assert after[key] is True  # снимок этого процесса сброшен сразу, без перезапуска
    assert (row.enabled, row.updated_by) == (True, owner.user_id)
    assert await audit_count(admin, "platform.feature_flag.updated", owner.user_id) == 1


async def test_admin_client_config_is_validated_and_audited(
    admin: Admin, restore_config: None
) -> None:
    owner = await staff(admin, "admin")
    async with admin.client(client_ip()) as client:
        assert await login(client, owner) == 302
        overview = await client.get("/admin/client-config")
        assert overview.status_code == 200
        assert "TELEGRAM_SUPPORT_USERNAME" in overview.text  # значение окружения — только чтение
        bad = await client.post(
            "/admin/client-config-record/edit/min_versions", data={"value": '{"ios": "latest"}'}
        )
        assert bad.status_code == 400
        missing_text = await client.post(
            "/admin/client-config-record/edit/legal_versions",
            data={"value": json.dumps({"terms": "no-such-version", "privacy": "draft-1"})},
        )
        assert missing_text.status_code == 400  # версии без текста в content/legal не бывает
        # ios: тестовые клиенты ходят как tma, минимальная версия ios им не мешает
        good = await client.post(
            "/admin/client-config-record/edit/min_versions", data={"value": '{"ios": "9.1"}'}
        )
        assert good.status_code == 302, good.text[:500]
        served = (await client.get("/api/v1/client-config")).json()["min_versions"]
    assert served["ios"] == "9.1"
    assert await audit_count(admin, "platform.client_config.updated", owner.user_id) == 1


async def test_admin_founding_goes_through_use_case(admin: Admin) -> None:
    owner = await staff(admin, "admin")
    profile_id = new_id()
    async with admin.container() as request:
        session = await request.get(AsyncSession)
        user_id = await insert_user(session, telegram_id=new_telegram_id())
        await session.execute(
            text(
                "INSERT INTO specialists.profiles (id, user_id, kind, status, display_name,"
                " city_id, created_at, published_at, version) SELECT :id, :user, 'pro',"
                " 'published', 'Founding', c.id, now(), now(), 1 FROM geo.cities c"
                " WHERE c.slug = 'novi-sad'"
            ),
            {"id": profile_id, "user": user_id},
        )
        await session.commit()
    engine = await admin.engine()

    async def founding() -> bool:
        async with engine.connect() as conn:
            return bool(
                await conn.scalar(
                    text("SELECT is_founding FROM specialists.profiles WHERE id = :id"),
                    {"id": profile_id},
                )
            )

    async with admin.client(client_ip()) as client:
        assert await login(client, owner) == 302
        marked = await client.get(
            "/admin/profile-row/action/founding-on", params={"pks": str(profile_id)}
        )
        assert marked.status_code == 302
        assert await founding()
        again = await client.get(
            "/admin/profile-row/action/founding-on", params={"pks": str(profile_id)}
        )
        assert again.status_code == 302  # повтор — без второй записи в аудите
        unmarked = await client.get(
            "/admin/profile-row/action/founding-off", params={"pks": str(profile_id)}
        )
        assert unmarked.status_code == 302
    assert not await founding()
    assert await audit_count(admin, "specialists.profile.founding_marked", owner.user_id) == 1
    assert await audit_count(admin, "specialists.profile.founding_unmarked", owner.user_id) == 1


def _category(slug: str, name: str, *, sort_order: int) -> CategorySeed:
    return CategorySeed(
        slug=slug,
        name=LocalizedText({Locale.RU: name, Locale.SR_CYRL: name}),
        icon=None,
        risk_level=RiskLevel.NORMAL,
        sort_order=sort_order,
        price_hints={},
        synonyms=(),
        tags=(
            TagSeed(
                slug=f"{slug}-tag",
                name=LocalizedText({Locale.RU: f"{name} тег", Locale.SR_CYRL: f"{name} таг"}),
            ),
        ),
        children=(),
    )


def _city(slug: str, name: str, *, sort_order: int) -> CitySeed:
    center = GeoPoint(lat=45.25, lon=19.84)
    return CitySeed(
        slug=slug,
        name=LocalizedText({Locale.RU: name, Locale.SR_CYRL: name}),
        center=center,
        active=False,
        sort_order=sort_order,
        boundary_wkt=None,
        districts=(
            DistrictSeed(
                slug=f"{slug}-centar",
                kind=DistrictKind.MUNICIPALITY,
                parent=None,
                name=LocalizedText({Locale.RU: f"{name} центр", Locale.SR_CYRL: "Центар"}),
                aliases=(),
                center=center,
                boundary_wkt=None,
                source="test",
            ),
        ),
    )


async def test_seed_keeps_names_edited_in_admin(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    slug = f"admin-name-{new_id().hex[:8]}"
    uow = make_uow(db_session, procrastinate_app)
    catalog, geo = SqlCatalogWriter(db_session, uow), SqlGeoWriter(db_session, uow)
    async with uow:
        await catalog.import_taxonomy([_category(slug, "Сид", sort_order=1)])
        await geo.upsert_city(_city(slug, "Сид", sort_order=1))
    edited = {"ru": "Админка", "sr-Cyrl": "Админка", "sr-Latn": "Adminka"}
    async with uow:  # как правка формой админки: название и name_origin = admin
        for table in ("catalog.categories", "catalog.tags", "geo.cities", "geo.districts"):
            await db_session.execute(
                text(
                    f"UPDATE {table} SET name = CAST(:name AS jsonb), name_origin = 'admin'"
                    " WHERE slug LIKE :slug"
                ),
                {"name": json.dumps(edited), "slug": f"{slug}%"},
            )
    # сид изменился: новое название и порядок — строка «изменена», импорт её переписывает
    async with uow:
        result = await catalog.import_taxonomy([_category(slug, "Сид новый", sort_order=2)])
        await geo.upsert_city(_city(slug, "Сид новый", sort_order=2))
    assert result.updated == 1
    rows = (
        await db_session.execute(
            text(
                "SELECT 'category' AS kind, name, name_origin, sort_order FROM catalog.categories"
                " WHERE slug = :slug UNION ALL SELECT 'tag', name, name_origin, 0 FROM catalog.tags"
                " WHERE slug = :tag UNION ALL SELECT 'city', name, name_origin, sort_order"
                " FROM geo.cities WHERE slug = :slug UNION ALL SELECT 'district', name,"
                " name_origin, 0 FROM geo.districts WHERE slug = :district"
            ),
            {"slug": slug, "tag": f"{slug}-tag", "district": f"{slug}-centar"},
        )
    ).all()
    assert {row.kind for row in rows} == {"category", "tag", "city", "district"}
    for row in rows:
        assert (row.name, row.name_origin) == (edited, "admin"), row.kind
    assert {row.kind: row.sort_order for row in rows if row.kind in {"category", "city"}} == {
        "category": 2,
        "city": 2,
    }
    # строка, название которой ведёт сид, следует за сидом, как раньше
    async with uow:
        await db_session.execute(
            text("UPDATE catalog.tags SET name_origin = 'seed' WHERE slug = :tag"),
            {"tag": f"{slug}-tag"},
        )
    async with uow:
        await catalog.import_taxonomy([_category(slug, "Сид третий", sort_order=3)])
    tag_name = await db_session.scalar(
        text("SELECT name->>'ru' FROM catalog.tags WHERE slug = :tag"), {"tag": f"{slug}-tag"}
    )
    assert tag_name == "Сид третий тег"
